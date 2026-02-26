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
    _extract_images_from_html,
    _deduplicate_fb_images,
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
                    const mainContainer = document.querySelector('div[data-pagelet="GlimpseReelVideoPlayer"]')
                        || document.querySelector('div[role="main"]')
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
                    
                    // Comprehensive View Count search - Prioritize counts with units
                    const fullText = mainContainer.innerText || "";
                    const viewMatches = fullText.match(/(\d[\d.,\s]*(?:[KMkm]|mil|mille|millones?|millón|million)?)\s*(?:views?|visualizaciones|reproducciones|plays?|vistas|vues?|visualizzazioni|visualizações|reprod\.)/gi);
                    if (viewMatches) {
                        // Sort by length to pick "17 millones" over "1.1K" if both exist in container
                        viewMatches.sort((a, b) => b.length - a.length);
                        data.view_candidates = viewMatches;
                    }

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
                    const seenSrcs = new Set();
                    const allImages = [];

                    // Broad selectors for images that are part of the post content
                    const mediaSelectors = [
                        'div[data-ad-comet-preview="message"] + div img', // Standard post images
                        'div[role="article"] img[src*="fbcdn"]',
                        'div[role="main"] img[src*="fbcdn"]',
                        'a[href*="/photo/"] img',
                        'a[href*="/photos/"] img',
                        'div[class*="photo"] img',
                        'img[src*="fbcdn"][alt]',
                    ];

                    for (const sel of mediaSelectors) {
                        mainContainer.querySelectorAll(sel).forEach(img => {
                            const src = img.src || '';
                            if (src && src.includes('fbcdn') && !seenSrcs.has(src)) {
                                // Filter out tiny thumbnails (profile pics are usually smaller than 100x100 in posts)
                                // but post images are much larger
                                const width = img.naturalWidth || img.width || 0;
                                const height = img.naturalHeight || img.height || 0;
                                
                                // Some FB layouts don't have dims immediately, but we can check the URL for clue or just keep if it looks like a content image
                                // Profile images usually have /cp/ or "profile" in URL
                                if (!src.includes('/cp/') && !src.includes('profile')) {
                                    if (width > 120 || height > 120 || (width === 0 && height === 0)) {
                                        seenSrcs.add(src);
                                        allImages.push({
                                            src: src,
                                            alt: img.alt || '',
                                            width: width,
                                            height: height,
                                        });
                                    }
                                }
                            }
                        });
                    }

                    // Count photo links (each represents an image in a gallery)
                    const photoLinks = new Set();
                    mainContainer.querySelectorAll('a[href*="/photo/"], a[href*="/photos/"]').forEach(a => {
                        const href = a.getAttribute('href') || '';
                        if (href && !href.includes('profile')) {
                            // Extract the base photo ID/URL to avoid counting duplicates
                            const photoId = href.split('?')[0];
                            photoLinks.add(photoId);
                        }
                    });
                    data.photo_link_count = photoLinks.size;

                    // Gallery indicator ("+X")
                    const moreImagesEl = mainContainer.querySelector('div[class*="photo"] span:not(:empty)');
                    if (moreImagesEl && moreImagesEl.innerText.includes('+')) {
                        const plusNum = parseInt(moreImagesEl.innerText.replace('+', ''));
                        if (!isNaN(plusNum)) data.gallery_plus_count = plusNum;
                    }

                    data.all_images = allImages;
                    data.image_count = allImages.length;

                    // ---- POST TYPE DETECTION ----
                    if (data.has_video) {
                        data.post_type = 'video';
                    } else if (data.photo_link_count > 1 || allImages.length > 1 || data.gallery_plus_count) {
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

                # Post type synchronization
                # Deduplicate DOM-found images first
                images = _deduplicate_fb_images([img["src"] for img in js_data.get("all_images", [])])
                image_count = len(images)
                photo_link_count = js_data.get("photo_link_count", 0)
                gallery_plus = js_data.get("gallery_plus_count", 0)
                has_video = js_data.get("has_video", False)

                # Use final extracted counts to decide post_type
                if has_video:
                    final_type = "video"
                elif image_count > 1 or photo_link_count > 1 or gallery_plus > 0:
                    final_type = "multi_image"
                elif image_count == 1 or photo_link_count == 1 or scraped_data.get("og_image"):
                    final_type = "single_image"
                else:
                    final_type = "text"

                scraped_data["post_type"] = final_type

                # Final images list
                if images:
                    scraped_data["images"] = images
                    scraped_data["image_count"] = image_count
                elif scraped_data.get("og_image"):
                    scraped_data["images"] = [scraped_data["og_image"]]
                    scraped_data["image_count"] = 1
                else:
                    scraped_data["images"] = []
                    scraped_data["image_count"] = 0

                scraped_data["photo_link_count"] = photo_link_count
                if gallery_plus:
                    scraped_data["gallery_plus_count"] = gallery_plus


                # Parse aria-labels and engagement_texts for engagement
                all_texts = (js_data.get("aria_labels") or []) + (js_data.get("engagement_texts") or [])
                for text in all_texts:
                    low_text = text.lower()
                    if "mira quién ha reaccionado" in low_text or "consulta quién reaccionó" in low_text:
                        continue
                    
                    # Reactions
                    total_r = _extract_reactions_count_from_text(text)
                    if total_r:
                        old_v = _normalize_count(scraped_data.get("reactions"), scraped_data.get("reactions_context")) or 0
                        new_v = _normalize_count(total_r, text) or 0
                        if new_v > old_v:
                            scraped_data["reactions"] = total_r
                            scraped_data["reactions_context"] = text
                    
                    # Comments
                    total_c = _extract_comments_count_from_text(text)
                    if total_c:
                        old_v = _normalize_count(scraped_data.get("comments")) or 0
                        new_v = _normalize_count(total_c) or 0
                        if new_v > old_v:
                            scraped_data["comments"] = total_c
                    
                    # Views
                    total_v = _extract_views_count_from_text(text)
                    if total_v:
                        old_v = _normalize_count(scraped_data.get("views")) or 0
                        new_v = _normalize_count(total_v) or 0
                        if new_v > old_v:
                            scraped_data["views"] = total_v
                    
                    # Shares
                    total_s = _extract_shares_count_from_text(text)
                    if total_s:
                        old_v = _normalize_count(scraped_data.get("shares")) or 0
                        new_v = _normalize_count(total_s) or 0
                        if new_v > old_v:
                            scraped_data["shares"] = total_s

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
                for k, func in [("reactions", _extract_reactions_count_from_text), 
                                ("comments", _extract_comments_count_from_text), 
                                ("shares", _extract_shares_count_from_text),
                                ("views", _extract_views_count_from_text)]:
                    val = func(page_text)
                    if val:
                        curr = scraped_data.get(k)
                        if not curr or _normalize_count(str(val)) > _normalize_count(str(curr)):
                            scraped_data[k] = str(val)
            except Exception as e:
                self.logger.warning(f"Page text fallback error: {e}")

            # ---- LAYER 5: GraphQL JSON EMBEDDED IN HTML (Engagement) ----
            if page_html:
                try:
                    embedded = _extract_engagement_from_html(page_html)
                    for k in ["reactions", "comments", "shares", "views"]:
                        val = embedded.get(k)
                        if val:
                            curr = scraped_data.get(k)
                            if not curr or _normalize_count(str(val)) > _normalize_count(str(curr)):
                                scraped_data[k] = str(val)
                    if embedded:
                        self.logger.info(f"GraphQL HTML extraction found: {embedded}")
                except Exception as e:
                    self.logger.warning(f"GraphQL HTML extraction error: {e}")

            # ---- LAYER 5b: VISIBLE TEXT PATTERNS IN HTML ----
            if page_html:
                try:
                    visible = _extract_engagement_from_visible_text(page_html)
                    for k in ["reactions", "comments", "shares", "views"]:
                        val = visible.get(k)
                        if val:
                            curr = scraped_data.get(k)
                            if not curr or _normalize_count(str(val)) > _normalize_count(str(curr)):
                                scraped_data[k] = str(val)
                    self.logger.info(f"Visible text extraction found: {visible}")
                except Exception as e:
                    self.logger.warning(f"Visible text extraction error: {e}")

            # ---- LAYER 6: GraphQL JSON IMAGE EXTRACTION ----
            # Facebook embeds ALL gallery image URIs in inline script JSON.
            # This works reliably even without cookies / login, unlike the DOM.
            if page_html:
                try:
                    html_images = _extract_images_from_html(page_html)
                    self.logger.info(f"GraphQL image extraction found {len(html_images)} images")

                    if html_images:
                        # Deduplicate GraphQL images (already done in _extract_images_from_html, but safely re-run)
                        html_images = _deduplicate_fb_images(html_images)
                        
                        # Merge with any DOM-found images: prefer the HTML set if larger
                        dom_images = scraped_data.get("images", [])
                        # Use HTML-extracted if it provides more (it should for galleries)
                        if len(html_images) >= len(dom_images):
                            scraped_data["images"] = html_images
                            scraped_data["image_count"] = len(html_images)
                            self.logger.info(f"Using deduplicated GraphQL images ({len(html_images)}) over DOM images ({len(dom_images)})")

                        # Re-evaluate post_type with the richer image set
                        new_count = scraped_data.get("image_count", 0)
                        has_video = scraped_data.get("video_src") or scraped_data.get("og_video")
                        if has_video:
                            scraped_data["post_type"] = "video"
                        elif new_count > 1:
                            scraped_data["post_type"] = "multi_image"
                        elif new_count == 1:
                            scraped_data["post_type"] = "single_image"
                        # else keep whatever was set before

                except Exception as e:
                    self.logger.warning(f"GraphQL image extraction error: {e}")
                    html_images = []

            # ---- FINAL RE-DEDUPLICATION AND NORMALIZATION ----
            # Ensure final images list is clean and counts are correct
            final_images = _deduplicate_fb_images(scraped_data.get("images", []))
            scraped_data["images"] = final_images
            scraped_data["image_count"] = len(final_images) or 0
            
            # Re-update post_type after all layers and final deduplication
            has_video = scraped_data.get("video_src") or scraped_data.get("og_video")
            if has_video:
                scraped_data["post_type"] = "video"
            elif scraped_data["image_count"] > 1:
                scraped_data["post_type"] = "multi_image"
            elif scraped_data["image_count"] == 1:
                scraped_data["post_type"] = "single_image"
            elif not scraped_data.get("post_type"):
                scraped_data["post_type"] = "text"
            for field in ["reactions", "comments", "shares", "views"]:
                raw = scraped_data.get(field)
                if raw:
                    normalized = _normalize_count(str(raw))
                    if normalized is not None:
                        scraped_data[f"{field}_count"] = normalized

            # ---- CONSTRUCT FINAL CLEAN DATA ----
            final_data = {
                "task_id": scraped_data.get("task_id"),
                "requested_url": scraped_data.get("requested_url"),
                "final_url": self.page.url if self.page else url,
                "scraped_at": scraped_data.get("scraped_at"),
                "content_type": "post",
                "post_type": scraped_data.get("post_type"),
                "username": scraped_data.get("username"),
                "caption": scraped_data.get("caption"),
                "post_date": scraped_data.get("post_date"),
            }

            # Metrics - Ensure they are always numbers
            final_data["reactions_count"] = scraped_data.get("reactions_count", 0)
            final_data["comments_count"] = scraped_data.get("comments_count", 0)
            final_data["shares_count"] = scraped_data.get("shares_count", 0)
            final_data["views_count"] = scraped_data.get("views_count", 0)

            # Move secondary media info to a sub-block to avoid noise
            final_data["media"] = {
                "images": scraped_data.get("images", []),
                "image_count": scraped_data.get("image_count", 0),
                "video_url": scraped_data.get("video_src") or scraped_data.get("og_video_url"),
                "video_duration": scraped_data.get("video_duration_seconds"),
                "has_video": scraped_data.get("post_type") == "video",
                "gallery_plus_count": scraped_data.get("gallery_plus_count")
            }

            # Debug block
            debug_info = scraped_data.get("_debug", {})
            if page_html:
                debug_info["full_html"] = page_html
            debug_info["metrics_raw"] = {
                "reactions": scraped_data.get("reactions"),
                "comments": scraped_data.get("comments"),
                "shares": scraped_data.get("shares"),
                "views": scraped_data.get("views"),
                "reactions_context": scraped_data.get("reactions_context")
            }
            final_data["_debug"] = debug_info

            # Standardize ROOT fields only
            ROOT_KEYS = [
                "task_id", "requested_url", "final_url", "scraped_at", 
                "content_type", "post_type", "username", "caption", "post_date",
                "reactions_count", "comments_count", "shares_count", "views_count",
                "media", "_debug"
            ]
            
            # HARD CLEAN: Absolute whitelist of root keys
            strict_data = {k: final_data[k] for k in ROOT_KEYS if k in final_data and final_data[k] is not None}

            self.logger.info(f"Extraction complete (Post). Metrics: R={strict_data.get('reactions_count')} C={strict_data.get('comments_count')} S={strict_data.get('shares_count')} V={strict_data.get('views_count')}")

            return {
                "status": "success",
                "data": strict_data
            }

        except Exception as e:
            self.logger.error(f"FacebookPostScraper failed: {str(e)}", exc_info=True)
            return self.format_error(str(e))
