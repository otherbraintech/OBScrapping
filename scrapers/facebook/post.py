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
    _normalize_count,
)

OG_TAGS = [
    "og:title", "og:description", "og:image", "og:url",
    "og:video", "og:video:url", "og:video:secure_url",
    "og:video:type", "og:video:width", "og:video:height",
    "og:type", "og:site_name"
]

class FacebookPostScraper(FacebookBaseScraper):

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
            # ---- NAVIGATE ----
            self.logger.info("Navigating to page...")
            try:
                await self.page.goto(url, wait_until="networkidle", timeout=60000)
            except Exception:
                self.logger.warning("Navigation timed out, proceeding anyway...")

            await asyncio.sleep(extra_wait if extra_wait > 0 else 3)

            # ---- CHECK FOR HARD BLOCK ----
            restriction_msg = await self.check_restricted()
            if restriction_msg:
                return self.format_error(restriction_msg)

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

            # ---- LAYER 2: PARSE OG TITLE FOR ENGAGEMENT ----
            og_title = scraped_data.get("og_title", "")
            if og_title:
                self.logger.info(f"Parsing OG title: {og_title[:100]}")
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
                # Author and caption from title
                if "|" in og_title:
                    parts = og_title.split("|")
                    scraped_data["author_from_title"] = parts[-1].strip()
                    if len(parts) >= 3:
                        scraped_data["clean_caption"] = parts[1].strip()
                    elif len(parts) == 2:
                        scraped_data["clean_caption"] = parts[0].strip()

            # ---- LAYER 3: JS EVALUATION ----
            self.logger.info("Running JS extraction...")
            try:
                js_data = await self.page.evaluate("""() => {
                    const data = {};
                    const mainContainer = document.querySelector('div[role="main"]')
                        || document.querySelector('div[role="article"]')
                        || document;

                    // Aria labels
                    const allElements = mainContainer.querySelectorAll('[aria-label]');
                    const ariaLabels = [];
                    allElements.forEach(el => {
                        const label = el.getAttribute('aria-label');
                        if (label) ariaLabels.push(label);
                    });
                    data.aria_labels = ariaLabels;

                    // Engagement texts from spans
                    const engagementTexts = [];
                    mainContainer.querySelectorAll('span').forEach(span => {
                        const text = span.innerText ? span.innerText.trim() : '';
                        if (text && text.length < 150 && /\\d/.test(text)) {
                            engagementTexts.push(text);
                        }
                    });
                    data.engagement_texts = engagementTexts;

                    // Button texts
                    const buttonTexts = [];
                    mainContainer.querySelectorAll('div[role="button"]').forEach(div => {
                        const text = div.innerText ? div.innerText.trim() : '';
                        if (text && text.length < 100) buttonTexts.push(text);
                    });
                    data.button_texts = buttonTexts;

                    // Video info
                    const video = mainContainer.querySelector('video');
                    if (video) {
                        data.video_duration = video.duration || null;
                        data.video_src = video.src || null;
                        data.video_poster = video.poster || null;
                    }

                    // Post date from aria-label on time links
                    const timeLinks = mainContainer.querySelectorAll('a[role="link"]');
                    timeLinks.forEach(link => {
                        const ariaLabel = link.getAttribute('aria-label');
                        if (ariaLabel && /\\d/.test(ariaLabel) && (
                            /hora|minuto|día|semana|mes|año|hour|minute|day|week|month|year|ago|hace|ayer|yesterday/i.test(ariaLabel) ||
                            /\\d{1,2}\\s*(de\\s+)?\\w+\\s*(de\\s+)?\\d{4}/i.test(ariaLabel)
                        )) {
                            data.post_date = ariaLabel;
                        }
                    });

                    // Caption / post text
                    const captionEl = mainContainer.querySelector('[data-ad-comet-preview="message"]')
                        || mainContainer.querySelector('div[dir="auto"] > div[dir="auto"]')
                        || mainContainer.querySelector('div[data-testid="post_message"]');
                    if (captionEl) {
                        data.caption = captionEl.innerText ? captionEl.innerText.trim() : null;
                    }

                    // Username
                    const usernameEl = mainContainer.querySelector('h2 a[role="link"]')
                        || mainContainer.querySelector('h3 a[role="link"]')
                        || mainContainer.querySelector('strong a[role="link"]');
                    if (usernameEl) {
                        data.username = usernameEl.innerText ? usernameEl.innerText.trim() : null;
                    }

                    return data;
                }""")

                self.logger.info(
                    f"JS found: {len(js_data.get('aria_labels', []))} aria-labels, "
                    f"{len(js_data.get('engagement_texts', []))} engagement texts"
                )

                # Post date & caption & username
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

            # ---- LAYER 4: PAGE TEXT FALLBACK ----
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

            # ---- LAYER 5: HTML EMBEDDED PATTERNS ----
            if page_html and not scraped_data.get("reactions"):
                try:
                    embedded = _extract_reactions_count_from_html(page_html)
                    if embedded:
                        scraped_data["reactions"] = embedded
                except Exception:
                    pass

            # ---- BUILD FINAL OUTPUT ----
            # Normalize final counts to integers
            for field in ["reactions", "comments", "shares", "views"]:
                raw = scraped_data.get(field)
                if raw:
                    normalized = _normalize_count(str(raw))
                    if normalized is not None:
                        scraped_data[f"{field}_count"] = normalized

            # Remove None values
            scraped_data = {k: v for k, v in scraped_data.items() if v is not None}

            self.logger.info(f"Extraction complete. Keys: {list(scraped_data.keys())}")

            return {
                "status": "success",
                "data": scraped_data
            }

        except Exception as e:
            self.logger.error(f"FacebookPostScraper failed: {str(e)}", exc_info=True)
            return self.format_error(str(e))
