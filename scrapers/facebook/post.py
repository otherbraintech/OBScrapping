import asyncio
import re
import html as _html
from datetime import datetime
from typing import Dict, Any, Optional

from .base import FacebookBaseScraper
from .utils import (
    _extract_reactions_count_from_text,
    _extract_comments_count_from_text,
    _extract_shares_count_from_text,
    _extract_views_count_from_text,
    _extract_reactions_count_from_html,
    _extract_engagement_from_html,
    _normalize_count,
)

OG_TAGS = [
    "og:title", "og:description", "og:image", "og:url",
    "og:video", "og:video:url", "og:video:secure_url",
    "og:video:type", "og:video:width", "og:video:height",
    "og:type", "og:site_name"
]

class FacebookPostScraper(FacebookBaseScraper):

    async def _scroll_page(self):
        """Scroll to trigger lazy loading of engagement data."""
        if not self.page:
            return
        try:
            for _ in range(3):
                await self.page.evaluate("window.scrollBy(0, 600)")
                await asyncio.sleep(0.8)
            await self.page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1.0)
        except Exception:
            pass

    async def run(self, url: str, **kwargs) -> Dict[str, Any]:
        self.logger.info(f"Running FacebookPostScraper for {url}")

        debug_raw: bool = kwargs.get("debug_raw", False)
        extra_wait: float = kwargs.get("extra_wait_seconds", 2.0)

        scraped_data: Dict[str, Any] = {
            "task_id": self.task_id,
            "requested_url": url,
            "scraped_at": datetime.utcnow().isoformat(),
        }

        if not self.page:
            return self.format_error("Browser not initialized")

        try:
            # ---- INJECT COOKIES before navigation ----
            await self.inject_cookies()

            # ---- NAVIGATE ----
            self.logger.info("Navigating to page...")
            try:
                await self.page.goto(url, wait_until="networkidle", timeout=60000)
            except Exception:
                self.logger.warning("Navigation timed out, proceeding anyway...")

            # Wait for page to settle
            await asyncio.sleep(max(extra_wait, 3.0))

            # ---- CHECK FOR HARD BLOCK ----
            restriction_msg = await self.check_restricted()
            if restriction_msg:
                return self.format_error(restriction_msg)

            # ---- SCROLL to trigger lazy loading ----
            await self._scroll_page()

            # ---- LAYER 1: OG META TAGS ----
            self.logger.info("Extracting OG meta tags...")
            try:
                head_val = await self.page.evaluate("document.head.innerHTML")
                head_html: str = str(head_val) if head_val else ""
            except Exception:
                head_html = ""

            page_html = await self.page.content()
            scraped_data["diagnostic_html_length"] = len(page_html)

            og_found = 0
            for tag in OG_TAGS:
                try:
                    patterns = [
                        f'<meta[^>]+property="{tag}"[^>]+content="([^"]+)"',
                        f'<meta[^>]+content="([^"]+)"[^>]+property="{tag}"'
                    ]
                    found_val = None
                    for pat in patterns:
                        m = re.search(pat, head_html, re.IGNORECASE)
                        if m:
                            found_val = _html.unescape(m.group(1))
                            break
                    if not found_val:
                        el = self.page.locator(f'meta[property="{tag}"]')
                        if await el.count() > 0:
                            found_val = await el.first.get_attribute("content")
                    if found_val:
                        key = tag.replace(":", "_").replace(".", "_")
                        scraped_data[key] = found_val
                        og_found += 1
                except Exception as e:
                    self.logger.warning(f"OG tag {tag} error: {e}")

            self.logger.info(f"Found {og_found} OG tags")

            # Standard meta description
            try:
                meta_desc = self.page.locator('meta[name="description"]')
                if await meta_desc.count() > 0:
                    scraped_data["meta_description"] = await meta_desc.first.get_attribute("content")
            except Exception:
                pass

            # Page title
            try:
                scraped_data["page_title"] = await self.page.title()
            except Exception:
                pass

            # ---- LAYER 2: STRUCTURED FIELDS FROM OG DATA ----
            # Caption: og:description is the post text, page title has "Caption - Author" format
            og_title = scraped_data.get("og_title", "")
            og_description = scraped_data.get("og_description", "")
            page_title = scraped_data.get("page_title", "")

            # Caption = og:description (most reliable for post text)
            if og_description:
                scraped_data["caption"] = og_description

            # Username: extract from page title "Caption - Author" or from og:title
            # page_title format: "Caption - Author" (for posts)
            # og:title is often just the author name
            if og_title and not scraped_data.get("username"):
                # og:title tends to be the Page/Author name for posts
                scraped_data["username"] = og_title

            if page_title and " - " in page_title:
                parts = page_title.rsplit(" - ", 1)
                if len(parts) == 2:
                    scraped_data["username"] = parts[1].strip()
                    if not scraped_data.get("caption"):
                        scraped_data["caption"] = parts[0].strip()

            # Parse OG title for engagement (some posts embed counts in og:title)
            if og_title:
                r = _extract_reactions_count_from_text(og_title)
                if r:
                    scraped_data["reactions"] = r
                    scraped_data["reactions_context"] = og_title
                s = _extract_shares_count_from_text(og_title)
                if s:
                    scraped_data["shares"] = s
                c = _extract_comments_count_from_text(og_title)
                if c:
                    scraped_data["comments"] = c
                v = _extract_views_count_from_text(og_title)
                if v:
                    scraped_data["views"] = v

            # ---- LAYER 3: JS EVALUATION ----
            self.logger.info("Running JS extraction...")
            try:
                js_data = await self.page.evaluate("""() => {
                    const data = {};
                    const mainContainer = document.querySelector('div[role="main"]')
                        || document.querySelector('div[role="article"]')
                        || document;

                    // Aria labels
                    const ariaLabels = [];
                    mainContainer.querySelectorAll('[aria-label]').forEach(el => {
                        const label = el.getAttribute('aria-label');
                        if (label) ariaLabels.push(label);
                    });
                    data.aria_labels = ariaLabels;

                    // Engagement texts from spans with numbers
                    const engagementTexts = [];
                    mainContainer.querySelectorAll('span').forEach(span => {
                        const text = span.innerText ? span.innerText.trim() : '';
                        if (text && text.length < 150 && /\\d/.test(text)) {
                            engagementTexts.push(text);
                        }
                    });
                    data.engagement_texts = engagementTexts;

                    // Button texts (reaction/comment/share buttons)
                    const buttonTexts = [];
                    mainContainer.querySelectorAll('div[role="button"]').forEach(div => {
                        const text = div.innerText ? div.innerText.trim() : '';
                        if (text && text.length < 100) buttonTexts.push(text);
                    });
                    data.button_texts = buttonTexts;

                    // Video detection
                    const video = mainContainer.querySelector('video');
                    if (video) {
                        data.has_video = true;
                        data.video_src = video.src || null;
                        data.video_poster = video.poster || null;
                        data.video_duration = video.duration || null;
                    } else {
                        data.has_video = false;
                    }

                    // ---- ALL IMAGES EXTRACTION ----
                    // Collect all unique fbcdn images (these are actual post images)
                    const seenSrcs = new Set();
                    const allImages = [];

                    // Strategy 1: images inside the post media area
                    // Facebook wraps multi-image posts in a grid or carousel container
                    const mediaSelectors = [
                        'div[data-pagelet="MediaViewerPhoto"] img',
                        'div[role="img"] img[src*="fbcdn"]',
                        'a[href*="/photo/"] img[src*="fbcdn"]',
                        'a[href*="/photos/"] img[src*="fbcdn"]',
                        'div[class*="photo"] img[src*="fbcdn"]',
                        'img[src*="fbcdn"][alt]',
                    ];

                    for (const sel of mediaSelectors) {
                        mainContainer.querySelectorAll(sel).forEach(img => {
                            const src = img.src || '';
                            // Filter out tiny thumbnails (profile pics, icons)
                            // and only keep images with meaningful dimensions
                            if (src && src.includes('fbcdn') && !seenSrcs.has(src)) {
                                const width = img.naturalWidth || img.width || 0;
                                const height = img.naturalHeight || img.height || 0;
                                // Only include images that look like post content
                                if (width > 100 || height > 100 || (width === 0 && height === 0)) {
                                    seenSrcs.add(src);
                                    allImages.push({
                                        src: src,
                                        alt: img.alt || '',
                                        width: width,
                                        height: height,
                                    });
                                }
                            }
                        });
                        if (allImages.length > 1) break; // found gallery images, stop
                    }

                    // Also look for gallery count indicator ("X photos")
                    const galleryCountEl = mainContainer.querySelector('div[class*="photoCount"], span[class*="photoCount"]');
                    if (galleryCountEl) {
                        const countText = galleryCountEl.innerText || '';
                        const m = countText.match(/(\\d+)/);
                        if (m) data.gallery_count_indicator = parseInt(m[1]);
                    }

                    // Strategy 2: count <a> links to /photo/ pages (each = one image in gallery)
                    const photoLinks = new Set();
                    mainContainer.querySelectorAll('a[href*="/photo/"]').forEach(a => {
                        const href = a.getAttribute('href') || '';
                        if (href && !href.includes('profile')) photoLinks.add(href.split('?')[0]);
                    });
                    data.photo_link_count = photoLinks.size;

                    data.all_images = allImages;
                    data.image_count = allImages.length;

                    // ---- POST TYPE DETECTION ----
                    // priority: video > multi-image > single-image > text
                    if (data.has_video) {
                        data.post_type = 'video';
                    } else if (data.photo_link_count > 1 || allImages.length > 1) {
                        data.post_type = 'multi_image';
                    } else if (allImages.length === 1 || data.photo_link_count === 1) {
                        data.post_type = 'single_image';
                    } else {
                        data.post_type = 'text';
                    }

                    // Post date from aria-label on time links
                    mainContainer.querySelectorAll('a[role="link"]').forEach(link => {
                        const ariaLabel = link.getAttribute('aria-label');
                        if (ariaLabel && /\\d/.test(ariaLabel) && (
                            /hora|minuto|día|semana|mes|año|hour|minute|day|week|month|year|ago|hace|ayer|yesterday/i.test(ariaLabel) ||
                            /\\d{1,2}\\s*(de\\s+)?\\w+\\s*(de\\s+)?\\d{4}/i.test(ariaLabel)
                        )) {
                            data.post_date = ariaLabel;
                        }
                    });

                    // Caption from DOM
                    const captionEl = mainContainer.querySelector('[data-ad-comet-preview="message"]')
                        || mainContainer.querySelector('div[dir="auto"] > div[dir="auto"]')
                        || mainContainer.querySelector('div[data-testid="post_message"]');
                    if (captionEl) {
                        data.caption = captionEl.innerText ? captionEl.innerText.trim() : null;
                    }

                    // Username from DOM
                    const usernameEl = mainContainer.querySelector('h2 a[role="link"]')
                        || mainContainer.querySelector('h3 a[role="link"]')
                        || mainContainer.querySelector('strong a[role="link"]');
                    if (usernameEl) {
                        data.username = usernameEl.innerText ? usernameEl.innerText.trim() : null;
                    }

                    return data;
                }""")


                self.logger.info(
                    f"JS found {len(js_data.get('aria_labels', []))} aria-labels, "
                    f"{len(js_data.get('engagement_texts', []))} engagement texts"
                )

                # Log engagement-related labels for debugging
                for label in js_data.get("aria_labels", []):
                    if any(kw in label.lower() for kw in ['gusta', 'comenta', 'compartid', 'reacci', 'reaction', 'comment', 'share', 'view', 'personas']):
                        self.logger.info(f"  ARIA-LABEL: {label[:120]}")

                if js_data.get("post_date"):
                    scraped_data["post_date"] = js_data["post_date"]
                if js_data.get("caption"):
                    scraped_data["caption"] = js_data["caption"]
                if js_data.get("username"):
                    scraped_data["username"] = js_data["username"]
                if js_data.get("video_src"):
                    scraped_data["video_src"] = js_data["video_src"]
                    scraped_data["video_poster"] = js_data.get("video_poster")
                if js_data.get("video_duration"):
                    scraped_data["video_duration_seconds"] = js_data["video_duration"]

                # Post type (single_image / multi_image / video / text)
                if js_data.get("post_type"):
                    scraped_data["post_type"] = js_data["post_type"]

                # All images — list of {src, alt, width, height}
                all_images = js_data.get("all_images", [])
                if all_images:
                    scraped_data["images"] = [img["src"] for img in all_images]
                    scraped_data["image_count"] = len(all_images)
                elif scraped_data.get("og_image"):
                    # Fall back to og:image as the only image
                    scraped_data["images"] = [scraped_data["og_image"]]
                    scraped_data["image_count"] = 1

                # Diagnostic: photo link count (how many /photo/ anchors in DOM)
                scraped_data["photo_link_count"] = js_data.get("photo_link_count", 0)


                # Parse aria-labels for engagement
                for label in js_data.get("aria_labels", []):
                    low_label = label.lower()
                    if "mira quién ha reaccionado" in low_label or "consulta quién reaccionó" in low_label:
                        continue
                    total_r = _extract_reactions_count_from_text(label)
                    if total_r:
                        old_v = _normalize_count(scraped_data.get("reactions"), scraped_data.get("reactions_context")) or 0
                        new_v = _normalize_count(total_r, label) or 0
                        if new_v > old_v:
                            scraped_data["reactions"] = total_r
                            scraped_data["reactions_context"] = label
                    if not scraped_data.get("comments"):
                        c = _extract_comments_count_from_text(label)
                        if c:
                            scraped_data["comments"] = c
                    if not scraped_data.get("views"):
                        v = _extract_views_count_from_text(label)
                        if v:
                            scraped_data["views"] = v
                    if not scraped_data.get("shares"):
                        s = _extract_shares_count_from_text(label)
                        if s:
                            scraped_data["shares"] = s

                # Parse engagement texts + button texts
                all_texts = js_data.get("engagement_texts", []) + js_data.get("button_texts", [])
                for text in all_texts:
                    r_total = _extract_reactions_count_from_text(text)
                    if r_total:
                        old_v = _normalize_count(scraped_data.get("reactions"), scraped_data.get("reactions_context")) or 0
                        new_v = _normalize_count(r_total, text) or 0
                        if new_v > old_v:
                            scraped_data["reactions"] = r_total
                            scraped_data["reactions_context"] = text

                    c_total = _extract_comments_count_from_text(text)
                    if c_total:
                        old_v = _normalize_count(scraped_data.get("comments")) or 0
                        new_v = _normalize_count(c_total) or 0
                        if new_v > old_v:
                            scraped_data["comments"] = c_total

                    s_total = _extract_shares_count_from_text(text)
                    if s_total:
                        old_v = _normalize_count(scraped_data.get("shares")) or 0
                        new_v = _normalize_count(s_total) or 0
                        if new_v > old_v:
                            scraped_data["shares"] = s_total

                    v_total = _extract_views_count_from_text(text)
                    if v_total:
                        old_v = _normalize_count(scraped_data.get("views")) or 0
                        new_v = _normalize_count(v_total) or 0
                        if new_v > old_v:
                            scraped_data["views"] = v_total

            except Exception as e:
                self.logger.warning(f"JS extraction error: {e}")

            # ---- LAYER 4: PAGE BODY TEXT FALLBACK ----
            try:
                page_text = await self.page.inner_text("body")
                if not scraped_data.get("comments"):
                    m = re.search(r'([\d,.]+)\s*(?:comments?|comentarios)', page_text, re.IGNORECASE)
                    if m:
                        scraped_data["comments"] = m.group(1)
                if not scraped_data.get("reactions"):
                    m = re.search(r'([\d,.]+)\s*(?:personas\s*(?:más\s*)?reaccionaron|reacciones|reactions)', page_text, re.IGNORECASE)
                    if m:
                        scraped_data["reactions"] = m.group(1)
                if not scraped_data.get("shares"):
                    m = re.search(r'([\d,.]+)\s*(?:veces compartido|shares?)', page_text, re.IGNORECASE)
                    if m:
                        scraped_data["shares"] = m.group(1)
            except Exception as e:
                self.logger.warning(f"Page text fallback error: {e}")

            # ---- LAYER 5: GraphQL JSON EMBEDDED IN HTML ----
            # Facebook always embeds engagement data in inline <script> JSON,
            # even for anonymous users. This is the most reliable fallback.
            if page_html:
                try:
                    embedded = _extract_engagement_from_html(page_html)
                    if embedded.get("reactions") and not scraped_data.get("reactions"):
                        scraped_data["reactions"] = str(embedded["reactions"])
                    if embedded.get("comments") and not scraped_data.get("comments"):
                        scraped_data["comments"] = str(embedded["comments"])
                    if embedded.get("shares") and not scraped_data.get("shares"):
                        scraped_data["shares"] = str(embedded["shares"])
                    if embedded.get("views") and not scraped_data.get("views"):
                        scraped_data["views"] = str(embedded["views"])
                    if embedded:
                        self.logger.info(f"GraphQL HTML extraction found: {embedded}")
                except Exception as e:
                    self.logger.warning(f"GraphQL HTML extraction error: {e}")

            # ---- NORMALIZE COUNTS ----
            for field in ["reactions", "comments", "shares", "views"]:
                raw = scraped_data.get(field)
                if raw:
                    normalized = _normalize_count(str(raw))
                    if normalized is not None:
                        scraped_data[f"{field}_count"] = normalized

            # ---- CLEAN OUTPUT ----
            scraped_data = {k: v for k, v in scraped_data.items() if v is not None}
            self.logger.info(f"Extraction complete. Keys: {list(scraped_data.keys())}")

            return {
                "status": "success",
                "data": scraped_data
            }

        except Exception as e:
            self.logger.error(f"FacebookPostScraper failed: {str(e)}", exc_info=True)
            return self.format_error(str(e))
