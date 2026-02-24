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

class FacebookReelScraper(FacebookBaseScraper):

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
        self.logger.info(f"Running FacebookReelScraper for {url}")

        debug_raw: bool = kwargs.get("debug_raw", False)
        extra_wait: float = kwargs.get("extra_wait_seconds", 2.0)

        scraped_data: Dict[str, Any] = {
            "task_id": self.task_id,
            "requested_url": url,
            "scraped_at": datetime.utcnow().isoformat(),
            "post_type": "video"  # Reels are always videos
        }

        if not self.page:
            return self.format_error("Browser not initialized")

        try:
            # ---- INJECT COOKIES before navigation ----
            await self.inject_cookies()

            # ---- NAVIGATE ----
            self.logger.info("Navigating to Reel page...")
            try:
                # Reels URLs are sometimes tricky, Playwright handles redirects well
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
            og_title = scraped_data.get("og_title", "")
            og_description = scraped_data.get("og_description", "")
            page_title = scraped_data.get("page_title", "")

            # Caption = og:description
            if og_description:
                scraped_data["caption"] = og_description

            # Username — try multiple formats:
            # 1. page_title: "Caption - Page Name"
            # 2. og_title video format: "N réactions · N partages | Caption | Page Name"
            # 3. og_title plain format: "Page Name"
            if page_title and page_title != "Facebook" and " - " in page_title:
                parts = page_title.rsplit(" - ", 1)
                if len(parts) == 2:
                    scraped_data["username"] = parts[1].strip()
                    if not scraped_data.get("caption"):
                        scraped_data["caption"] = parts[0].strip()
            elif og_title:
                # Video og_title format: "N réactions · N partages | Caption | Page Name"
                # Or: "Caption | Page Name"
                if " | " in og_title:
                    parts = og_title.rsplit(" | ", 1)
                    scraped_data["username"] = parts[-1].strip()
                    if not scraped_data.get("caption") and len(parts) > 1:
                        # middle part (between first and last pipe) is the caption
                        inner = og_title.split(" | ")
                        # skip the first segment if it looks like engagement (has réactions/reactions)
                        start_idx = 1 if any(kw in inner[0].lower() for kw in ["réaction", "reaction", "partage", "share"]) else 0
                        scraped_data["caption"] = " | ".join(inner[start_idx:-1]).strip() or og_description
                elif not scraped_data.get("username"):
                    scraped_data["username"] = og_title

            # ---- VIDEO URL: populate video_url field (best available source) ----
            # Waterfall: og:video:secure_url > og:video:url > og:video > DOM video.src
            video_url = (
                scraped_data.get("og_video_secure_url")
                or scraped_data.get("og_video_url")
                or scraped_data.get("og_video")
                or scraped_data.get("video_src")
            )
            if video_url:
                scraped_data["video_url"] = video_url

            # Parse OG title for engagement
            if og_title:
                r = _extract_reactions_count_from_text(og_title)
                if r:
                    scraped_data["reactions"] = r
                    scraped_data["reactions_context"] = og_title
                s = _extract_shares_count_from_text(og_title)
                if s: scraped_data["shares"] = s
                c = _extract_comments_count_from_text(og_title)
                if c: scraped_data["comments"] = c
                v = _extract_views_count_from_text(og_title)
                if v: scraped_data["views"] = v

            # ---- LAYER 3: JS EVALUATION ----
            self.logger.info("Running JS extraction...")
            try:
                js_data = await self.page.evaluate("""() => {
                    const data = {};
                    const mainContainer = document.querySelector('div[role="main"]')
                        || document.querySelector('div[role="article"]')
                        || document.querySelector('div[data-pagelet="GlimpseReelVideoPlayer"]')
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

                    // Video detection
                    const video = mainContainer.querySelector('video');
                    if (video) {
                        data.has_video = true;
                        data.video_src = video.src || null;
                        data.video_poster = video.poster || null;
                        data.video_duration = video.duration || null;
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
                        || mainContainer.querySelector('div[id^="mount_0_0"] span[dir="auto"]');
                    if (captionEl) {
                        data.caption = captionEl.innerText ? captionEl.innerText.trim() : null;
                    }

                    // Username from DOM
                    const usernameEl = mainContainer.querySelector('h2 a[role="link"]')
                        || mainContainer.querySelector('span[role="link"] strong')
                        || mainContainer.querySelector('a[href*="/reel/"] + div span');
                    if (usernameEl) {
                        data.username = usernameEl.innerText ? usernameEl.innerText.trim() : null;
                    }

                    return data;
                }""")

                if js_data.get("post_date"):
                    scraped_data["post_date"] = js_data["post_date"]
                if js_data.get("caption"):
                    scraped_data["caption"] = js_data["caption"]
                if js_data.get("username"):
                    scraped_data["username"] = js_data["username"]
                if js_data.get("video_src"):
                    scraped_data["video_src"] = js_data["video_src"]
                    if not scraped_data.get("og_image"):
                        scraped_data["video_poster"] = js_data.get("video_poster")
                # Post type synchronization
                images = [img["src"] for img in js_data.get("all_images", [])] if "all_images" in js_data else []
                image_count = len(images)
                has_video = js_data.get("has_video", True) # Default true for reels

                if has_video:
                    scraped_data["post_type"] = "video"
                elif image_count > 1:
                    scraped_data["post_type"] = "multi_image"
                elif image_count == 1 or scraped_data.get("og_image"):
                    scraped_data["post_type"] = "single_image"
                else:
                    scraped_data["post_type"] = "text"

                # Final images list
                if images:
                    scraped_data["images"] = images
                    scraped_data["image_count"] = image_count
                elif scraped_data.get("og_image"):
                    scraped_data["images"] = [scraped_data["og_image"]]
                    scraped_data["image_count"] = 1

            except Exception as e:
                self.logger.warning(f"JS extraction error in Reels: {e}")

            # ---- LAYER 4: GraphQL JSON EMBEDDED IN HTML ----
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
                        self.logger.info(f"GraphQL Reels extraction found: {embedded}")
                except Exception as e:
                    self.logger.warning(f"GraphQL Reels extraction error: {e}")

            # ---- LAYER 5: HTML VIDEO URL SCAN ----
            # Extract .mp4 video URLs from inline fbcdn JSON (fallback if og:video empty)
            video_url_found = scraped_data.get("video_url")
            if not video_url_found and page_html:
                try:
                    mp4_pattern = re.compile(
                        r'https?:\\?/\\?/video[^"\' <>\s]+\.mp4[^"\' <>\s]*',
                        re.IGNORECASE
                    )
                    mp4_urls = []
                    seen_mp4: set = set()
                    for mp4m in mp4_pattern.finditer(page_html):
                        raw_mp4 = mp4m.group(0).replace("\\/", "/").rstrip('.,;)')
                        if raw_mp4 not in seen_mp4:
                            seen_mp4.add(raw_mp4)
                            mp4_urls.append(raw_mp4)
                    if mp4_urls:
                        scraped_data["video_url"] = mp4_urls[0]
                        scraped_data["video_url_all"] = mp4_urls
                        self.logger.info(f"HTML mp4 scan found {len(mp4_urls)} video URLs")
                except Exception as e:
                    self.logger.warning(f"HTML mp4 scan error: {e}")

            # ---- NORMALIZE COUNTS ----
            for field in ["reactions", "comments", "shares", "views"]:
                raw = scraped_data.get(field)
                if raw:
                    normalized = _normalize_count(str(raw))
                    if normalized is not None:
                        scraped_data[f"{field}_count"] = normalized

            # ---- DEBUG BLOCK (always included — remove once stable) ----
            try:
                scraped_data["_debug"] = {
                    "final_url": self.page.url if self.page else url,
                    "html_length": len(page_html) if page_html else 0,
                    "video_url_source": (
                        "og_video_secure_url" if scraped_data.get("og_video_secure_url")
                        else "og_video_url" if scraped_data.get("og_video_url")
                        else "og_video" if scraped_data.get("og_video")
                        else "dom" if scraped_data.get("video_src")
                        else "mp4_html_scan" if scraped_data.get("video_url")
                        else "none"
                    ),
                }
            except Exception as de:
                scraped_data["_debug"] = {"error": str(de)}

            # ---- CLEAN OUTPUT ----
            scraped_data = {k: v for k, v in scraped_data.items() if v is not None}
            return {
                "status": "success",
                "data": scraped_data
            }

        except Exception as e:
            self.logger.error(f"FacebookReelScraper failed: {str(e)}", exc_info=True)
            return self.format_error(str(e))
