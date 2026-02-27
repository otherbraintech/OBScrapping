import asyncio
import base64
import json
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
    _extract_engagement_from_visible_text,
    _deduplicate_fb_images,
    _normalize_count,
)
from .ai_utils import extract_metrics_with_ai

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

    def _extract_video_id(self, scraped_data: Dict[str, Any], html: str) -> Optional[str]:
        """Extract a stable numeric video ID from available sources."""
        # 1. From og:url (e.g. /reel/123/ or /videos/slug/123/)
        og_url = scraped_data.get("og_url", "")
        if og_url:
            # Look for 10+ digits at the end or after a common prefix
            m = re.search(r'/(?:reel|videos|video|watch|v)/(?:[^/]+/)*(\d{10,})', og_url)
            if m: return m.group(1)
            # Try matching just the digits at the end
            m_end = re.search(r'/(\d{10,})/?$', og_url)
            if m_end: return m_end.group(1)

        # 2. From requested_url
        req_url = scraped_data.get("requested_url", "")
        if req_url:
            m = re.search(r'/(?:reel|videos|video|watch|v)/(?:[^/]+/)*(\d{10,})', req_url)
            if m: return m.group(1)
            m_end = re.search(r'/(\d{10,})/?$', req_url)
            if m_end: return m_end.group(1)

        # 3. From HTML (e.g. "top_level_post_id":"123", "videoID":"123", etc.)
        patterns = [
            r'"top_level_post_id"\s*:\s*"(\d+)"', 
            r'"videoID"\s*:\s*"(\d+)"', 
            r'"itemID"\s*:\s*"(\d+)"',
            r'\bfbid=(\d+)\b',
            r'"ent_id"\s*:\s*"(\d+)"',
            r'"fbid"\s*:\s*"(\d+)"',
            # Specific pattern for the android intent URL often found in head
            r' Uzpf[a-zA-Z0-9]+:VK:(\d+)' 
        ]
        for pat in patterns:
            m = re.search(pat, html)
            if m: return m.group(1)
        
        # 4. Fallback search for ANY occurrence of /reel/ID or /videos/ID
        m_fallback = re.search(r'/(?:reel|videos|video|v)/(\d{10,})', html)
        if m_fallback: return m_fallback.group(1)
        
        return None

    async def run(self, url: str, **kwargs) -> Dict[str, Any]:
        self.logger.info(f"Running FacebookReelScraper for {url}")

        debug_raw: bool = kwargs.get("debug_raw", False)
        extra_wait: float = kwargs.get("extra_wait_seconds", 2.0)

        scraped_data: Dict[str, Any] = {
            "task_id": self.task_id,
            "requested_url": url,
            "scraped_at": datetime.utcnow().isoformat(),
            "post_type": "video",  # Reels are always videos
            "version": "1.0.8-fixed",
            "_debug": {}
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
            try:
                js_data = await self.page.evaluate(r"""() => {
                    const data = {};
                    // Start with restricted container but allow fallback to body for metrics
                    const playerContainer = document.querySelector('div[data-pagelet="GlimpseReelVideoPlayer"]')
                        || document.querySelector('div[role="main"]');
                    const mainContainer = playerContainer || document.body;

                    // Recursive text and aria collection
                    const allInfo = [];
                    const walk = (node) => {
                        if (node.nodeType === 1) { // Element
                            const aria = node.getAttribute('aria-label');
                            if (aria && aria.length < 150) allInfo.push(aria);
                            const text = node.innerText;
                            if (text && text.length < 150) allInfo.push(text);
                            node.childNodes.forEach(walk);
                        }
                    };
                    walk(mainContainer);
                    data.engagement_texts = [...new Set(allInfo)];
                    // Comprehensive View Count search - Search whole page but filter noise
                    const searchSource = document.body.innerText || "";
                    const viewMatches = searchSource.match(/(\d[\d.,\s]*(?:[KMkm]|mil|mille|millones?|millón|million)?)\s*(?:views?|visualizaciones|reproducciones|plays?|vistas|vues?|visualizzazioni|visualizações|reprod\.)/gi);
                    if (viewMatches) {
                        // Filter out matches that belong to "Suggested" or "Up Next" sections
                        const filteredMatches = viewMatches.filter(m => {
                            const low = m.toLowerCase();
                            // If it's a very large number, it's likely our video
                            if (low.includes('million') || low.includes('millón')) return true;
                            return true; // For now keep all, sort later
                        });
                        // Sort by magnitude: M > K > large numbers
                        filteredMatches.sort((a, b) => {
                            const valA = a.toLowerCase();
                            const valB = b.toLowerCase();
                            if ((valA.includes('m') || valA.includes('mill')) && !(valB.includes('m') || valB.includes('mill'))) return -1;
                            if (!(valA.includes('m') || valA.includes('mill')) && (valB.includes('m') || valB.includes('mill'))) return 1;
                            return b.length - a.length;
                        });
                        data.view_candidates = filteredMatches;
                    data._raw_search_source = searchSource.substring(0, 10000); // Sample noise
                    }

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
                images = _deduplicate_fb_images([img["src"] for img in js_data.get("all_images", [])]) if "all_images" in js_data else []
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

                # ---- Extract engagement from aria_labels and engagement_texts ----
                all_texts = (js_data.get("aria_labels") or []) + (js_data.get("engagement_texts") or [])
                for text in all_texts:
                    # Reactions
                    r = _extract_reactions_count_from_text(text)
                    if r:
                        curr = scraped_data.get("reactions")
                        if not curr or _normalize_count(r) > _normalize_count(str(curr)):
                            scraped_data["reactions"] = r
                    
                    # Comments
                    c = _extract_comments_count_from_text(text)
                    if c:
                        curr = scraped_data.get("comments")
                        if not curr or _normalize_count(c) > _normalize_count(str(curr)):
                            scraped_data["comments"] = c
                    
                    # Shares
                    s = _extract_shares_count_from_text(text)
                    if s:
                        curr = scraped_data.get("shares")
                        if not curr or _normalize_count(s) > _normalize_count(str(curr)):
                            scraped_data["shares"] = s

                    # Views
                    v = _extract_views_count_from_text(text)
                    if v:
                        curr = scraped_data.get("views")
                        if not curr or _normalize_count(v) > _normalize_count(str(curr)):
                            scraped_data["views"] = v
                
                # Check view candidates from the whole page text
                for candidate in js_data.get("view_candidates", []):
                    v = _extract_views_count_from_text(candidate)
                    if v:
                        curr = scraped_data.get("views")
                        if not curr or _normalize_count(v) > _normalize_count(str(curr)):
                            scraped_data["views"] = v

            except Exception as e:
                self.logger.warning(f"JS extraction error in Reels: {e}")

            # ---- LAYER 4: GraphQL JSON EMBEDDED IN HTML ----
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
                        self.logger.info(f"GraphQL Reels extraction found: {embedded}")
                except Exception as e:
                    self.logger.warning(f"GraphQL Reels extraction error: {e}")

            # ---- LAYER 4b: VISIBLE TEXT PATTERNS IN HTML ----
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

            # ---- LAYER 4c: GLOBAL Engagement SCAN (Python Last Resort) ----
            # If metrics are low or zero, scan the ENTIRE HTML for patterns
            if page_html:
                current_views_norm = _normalize_count(str(scraped_data.get("views", "0"))) or 0
                if current_views_norm < 10000:
                    v_pats = [r'([\d.,]+\s*(?:M|millions?|millón|mill|mil|mille))\s*(?:de\s+)?(?:vues?|views?|visualizaciones|repro)', 
                              r'(?:views?|vues?|visualizaciones|repro):\s*[^\d]*([\d.,]+\s*(?:M|millions?|millón|mill|mil|mille))']
                    for pat in v_pats:
                        for m in re.finditer(pat, page_html, re.IGNORECASE):
                            v = _normalize_count(m.group(1)); 
                            if v and v > current_views_norm: scraped_data["views"] = m.group(1); current_views_norm = v
                
                current_shares_norm = _normalize_count(str(scraped_data.get("shares", "0"))) or 0
                if current_shares_norm < 1:
                    s_pats = [r'([\d.,]+\s*[KMkm]?)\s*(?:de\s+)?(?:shares?|compartido|compartidos|partages?|repartages)', 
                              r'(?:shares?|compartido|compartidos|partages?|repartages):\s*[^\d]*([\d.,]+\s*[KMkm]?)']
                    for pat in s_pats:
                        for m in re.finditer(pat, page_html, re.IGNORECASE):
                            s = _normalize_count(m.group(1));
                            if s and s > current_shares_norm: scraped_data["shares"] = m.group(1); current_shares_norm = s

            # ---- LAYER 5: HTML VIDEO URL SCAN ----
            # Extract .mp4 video URLs — clean HTML entities, filter to target video only
            video_url_found = scraped_data.get("video_url")
            if not video_url_found and page_html:
                try:
                    # Extract target video ID from og_url (e.g. /videos/.../3597741687035400/)
                    target_video_id: Optional[str] = None
                    og_url = scraped_data.get("og_url", "")
                    vid_id_match = re.search(r'/(\d{10,})', og_url)
                    if vid_id_match:
                        target_video_id = vid_id_match.group(1)
                        self.logger.info(f"Target video_id: {target_video_id}")

                    # Find all .mp4 URLs (both clean and DASH-manifest encoded)
                    mp4_pattern = re.compile(
                        r'https?:(?:\\?/\\?/|//)?video[^"\'<>\s\u003C]+\.mp4[^"\'<>\s\u003C]*',
                        re.IGNORECASE
                    )

                    all_mp4: list = []
                    seen_mp4: set = set()

                    for mp4m in mp4_pattern.finditer(page_html):
                        raw = mp4m.group(0)

                        # Clean: unescape JSON slashes
                        url = raw.replace("\\/", "/")

                        # Clean: unescape HTML entities (&amp; → &, &#x3C; → <, etc.)
                        try:
                            url = _html.unescape(url)
                        except Exception:
                            pass

                        # Clean: strip DASH manifest XML junk
                        # Handles: </BaseURL, \u003C/BaseURL, \\u003C/BaseURL, etc.
                        url = re.sub(r'\\u003C.*$', '', url)      # literal \u003C...
                        url = re.sub(r'<.*$', '', url)            # actual < char
                        url = re.sub(r'%3C.*$', '', url, flags=re.IGNORECASE)  # URL-encoded <
                        url = url.rstrip('.,;)\'\"')

                        # Skip if clearly not a full URL
                        if not url.startswith("http"):
                            continue

                        # Skip audio-only streams (they can't be played standalone)
                        if "strext=1" in url or "audio" in url.split("?")[0]:
                            continue

                        if url not in seen_mp4:
                            seen_mp4.add(url)
                            all_mp4.append(url)

                    # Filter by folder: m367 = current reel, m366 = related/recommended videos
                    # Facebook organizes DASH segments this way: m367 is always the page's primary video
                    m367_urls = [u for u in all_mp4 if '/m367/' in u]
                    if m367_urls:
                        all_mp4 = m367_urls
                        self.logger.info(f"Filtered to {len(m367_urls)} m367 URLs (current reel)")
                    elif target_video_id:
                        # Fallback: try matching by video_id in URL
                        filtered = [u for u in all_mp4 if target_video_id in u]
                        if filtered:
                            all_mp4 = filtered

                    if all_mp4:
                        # Sort by quality: decode efg base64 or check tag= param
                        def quality_score(u: str) -> int:
                            """Extract resolution from URL. DASH URLs encode it
                            in base64 efg param; progressive URLs have tag= param."""
                            tag_str = ""
                            # Try tag= query parameter (progressive URLs)
                            tag_match = re.search(r'[&?]tag=([^&]+)', u)
                            if tag_match:
                                tag_str = tag_match.group(1)

                            # Try decoding base64 efg= parameter (DASH URLs)
                            efg_match = re.search(r'[&?]efg=([A-Za-z0-9_+/=%-]+)', u)
                            if efg_match:
                                try:
                                    import urllib.parse
                                    raw_efg = urllib.parse.unquote(efg_match.group(1))
                                    # Add padding if needed
                                    padded = raw_efg + '=' * (4 - len(raw_efg) % 4)
                                    decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
                                    efg_data = json.loads(decoded)
                                    tag_str = efg_data.get("vencode_tag", "") or efg_data.get("encode_tag", "")
                                except Exception:
                                    pass

                            # Extract resolution number from tag string
                            # e.g. "dash_vp9-basic-gen2_1080p" → 1080
                            res_match = re.search(r'(\d{3,4})p', tag_str)
                            if res_match:
                                return int(res_match.group(1))

                            # Fallback: check bitrate= parameter
                            br_match = re.search(r'[&?]bitrate=(\d+)', u)
                            if br_match:
                                return int(br_match.group(1)) // 10000  # normalize

                            return 0

                        all_mp4.sort(key=quality_score, reverse=True)
                        scraped_data["video_url"] = all_mp4[0]
                        scraped_data["video_url_all"] = all_mp4[:5]  # max 5 versions
                        self.logger.info(f"Best video_url (score={quality_score(all_mp4[0])}): {all_mp4[0][:80]}...")

                except Exception as e:
                    self.logger.warning(f"HTML mp4 scan error: {e}")

            # ---- NORMALIZE COUNTS ----
            for field in ["reactions", "comments", "shares", "views"]:
                raw = scraped_data.get(field)
                if raw:
                    normalized = _normalize_count(str(raw))
                    if normalized is not None:
                        scraped_data[f"{field}_count"] = normalized

            # ---- AI FALLBACK FOR MISSING METRICS ----
            # If basic metrics are all 0 or missing, try AI
            # Trigger AI fallback if basic metrics are missing or if views are 0
            # Reels should almost always have views, so 0 is a strong signal for fallback.
            if (scraped_data.get("reactions_count", 0) == 0 and 
                scraped_data.get("comments_count", 0) == 0 and 
                scraped_data.get("shares_count", 0) == 0) or \
               (scraped_data.get("views_count", 0) == 0):
                
                self.logger.info("Triggering AI fallback for metric extraction...")
                ai_results = await extract_metrics_with_ai(page_html or "", url)
                if ai_results:
                    for key, val in ai_results.items():
                        if val and val > 0:
                            # Only overwrite if AI found something positive and we had 0
                            current_val = scraped_data.get(key, 0)
                            if current_val == 0:
                                scraped_data[key] = val
                                scraped_data[f"{key}_ai_source"] = True
                                self.logger.info(f"AI found {key}: {val}")
                    
                    # Store AI confidence in debug
                    if "confidence" in ai_results:
                        scraped_data["ai_confidence"] = ai_results["confidence"]

            # ---- LAYER 6: POST INTERFACE FALLBACK (Redirection) ----
            # If views are STILL 0, navigate to alternative interfaces which usually show them
            if scraped_data.get("views_count", 0) == 0:
                video_id = self._extract_video_id(scraped_data, page_html or "")
                scraped_data["_debug"]["fallback_video_id"] = video_id
                
                if video_id:
                    # Try these URLs in order
                    fallback_urls = [
                        f"https://www.facebook.com/watch/?v={video_id}",
                        f"https://m.facebook.com/watch/?v={video_id}"
                    ]
                    
                    for f_url in fallback_urls:
                        self.logger.info(f"Views still 0. Falling back to Interface: {f_url}")
                        scraped_data["_debug"]["fallback_triggered"] = True
                        scraped_data["_debug"]["fallback_url_tried"] = f_url
                        
                        try:
                            # Navigate to the fallback URL
                            await self.page.goto(f_url, wait_until="domcontentloaded", timeout=20000)
                            await asyncio.sleep(4.0) # Wait for metrics to load
                            
                            # Re-run visible text extraction on the new page
                            new_html = await self.page.content()
                            visible_post = _extract_engagement_from_visible_text(new_html)
                            v_post = visible_post.get("views")
                            
                            if v_post:
                                v_norm = _normalize_count(str(v_post))
                                if v_norm and v_norm > 0:
                                    scraped_data["views"] = str(v_post)
                                    scraped_data["views_count"] = v_norm
                                    scraped_data["views_fallback_source"] = f"interface_{'mobile' if 'm.facebook' in f_url else 'desktop'}"
                                    self.logger.info(f"Fallback found views: {v_post}")
                                    break # Found it!
                            
                            # If visibility fails but it's mobile, try a specific scan for common mobile view class
                            if "m.facebook" in f_url:
                                m_views = re.search(r'([\d.,\s]+[KMkm]?)\s*(?:views|vues|reproducciones)', new_html, re.I)
                                if m_views:
                                    v_str = m_views.group(1).strip()
                                    v_norm = _normalize_count(v_str)
                                    if v_norm and v_norm > 0:
                                        scraped_data["views"] = v_str
                                        scraped_data["views_count"] = v_norm
                                        scraped_data["views_fallback_source"] = "mobile_regex_scan"
                                        self.logger.info(f"Mobile regex scan found views: {v_str}")
                                        break

                        except Exception as fe:
                            self.logger.warning(f"Fallback attempt failed for {f_url}: {fe}")
                            continue # Try next URL

                else:
                    self.logger.warning("Could not extract video_id for fallback.")

            # ---- DEBUG BLOCK (always included — remove once stable) ----
            try:
                debug_info: dict = scraped_data.get("_debug", {})
                debug_info.update({
                    "final_url": self.page.url if self.page else url,
                    "html_length": len(page_html) if page_html else 0,
                    "full_html": page_html,
                    "video_url_source": (
                        "og_video_secure_url" if scraped_data.get("og_video_secure_url")
                        else "og_video_url" if scraped_data.get("og_video_url")
                        else "og_video" if scraped_data.get("og_video")
                        else "dom" if scraped_data.get("video_src")
                        else "mp4_html_scan" if scraped_data.get("video_url")
                        else "none"
                    ),
                })

                # -- Diagnostic: scan HTML for engagement-related JSON keys --
                if page_html:
                    import re as _re
                    scan_patterns = {
                        "comment_count": r'"comment_count"\s*:\s*(\{[^}]{0,80}\}|\d+)',
                        "total_comment_count": r'"total_comment_count"\s*:\s*(\d+)',
                        "comments_total": r'"comments"\s*:\s*\{"total_count"\s*:\s*(\d+)',
                        "play_count": r'"play_count"\s*:\s*(\d+)',
                        "video_view_count": r'"video_view_count"\s*:\s*(\d+)',
                        "view_count": r'"view_count"\s*:\s*(\d+)',
                        "seen_by_count": r'"seen_by_count"\s*:\s*(\{[^}]{0,80}\}|\d+)',
                        "video_play_count": r'"video_play_count"\s*:\s*(\d+)',
                        "reaction_count": r'"reaction_count"\s*:\s*\{"count"\s*:\s*(\d+)',
                        "total_reaction_count": r'"total_reaction_count"\s*:\s*(\d+)',
                        "feedback_count": r'"feedback"\s*:\s*\{[^}]{0,200}',
                        "commentaire_visible": r'(\d[\d.,\s]*[KMkm]?)\s*(?:commentaires?|comments?)',
                        "vue_visible": r'(\d[\d.,\s]*[KMkm]?)\s*(?:vues?|views?|plays?)',
                    }
                    scan_results = {}
                    for label, pat in scan_patterns.items():
                        matches = _re.findall(pat, page_html[:500000])  # scan first 500KB
                        if matches:
                            scan_results[label] = matches[:3]  # max 3 matches per pattern
                    debug_info["html_engagement_scan"] = scan_results if scan_results else "no_matches"
                
                # Focused HTML snippet for troubleshooting
                if page_html:
                    # Find a relevant part of the DOM
                    marker = page_html.find('role="main"')
                    if marker == -1: marker = page_html.find('role="article"')
                    if marker == -1: marker = 0
                    debug_info["html_snippet"] = page_html[marker : marker + 5000]
                    debug_info["full_html"] = page_html

                scraped_data["_debug"] = debug_info
            except Exception as de:
                scraped_data["_debug"] = {"error": str(de)}

            # Normalize all metric counts
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
                "content_type": "reel",
                "username": scraped_data.get("username"),
                "caption": scraped_data.get("caption"),
                "post_date": scraped_data.get("post_date"),
            }

            # Metrics
            final_data["reactions_count"] = scraped_data.get("reactions_count", 0)
            final_data["comments_count"] = scraped_data.get("comments_count", 0)
            final_data["shares_count"] = scraped_data.get("shares_count", 0)
            final_data["views_count"] = scraped_data.get("views_count", 0)

            # Move secondary media info to a sub-block
            final_data["media"] = {
                "video_url": scraped_data.get("video_url") or scraped_data.get("video_src") or scraped_data.get("og_video_url"),
                "images": scraped_data.get("images", []),
                "image_count": scraped_data.get("image_count", 0),
                "video_id": scraped_data.get("target_video_id"),
                "og_video_width": scraped_data.get("og_video_width"),
                "og_video_height": scraped_data.get("og_video_height")
            }

            # Debug block
            debug_info = scraped_data.get("_debug", {})
            debug_info["metrics_raw"] = {
                "reactions": scraped_data.get("reactions"),
                "comments": scraped_data.get("comments"),
                "shares": scraped_data.get("shares"),
                "views": scraped_data.get("views")
            }
            final_data["_debug"] = debug_info

            # Standardize ROOT fields only
            ROOT_KEYS = [
                "task_id", "requested_url", "final_url", "scraped_at", 
                "content_type", "username", "caption", "post_date",
                "reactions_count", "comments_count", "shares_count", "views_count",
                "media", "version", "_debug"
            ]
            
            # HARD CLEAN: Absolute whitelist of root keys
            strict_data = {k: final_data[k] for k in ROOT_KEYS if k in final_data and final_data[k] is not None}

            self.logger.info(f"Extraction complete (Reel). Metrics: R={strict_data.get('reactions_count')} C={strict_data.get('comments_count')} S={strict_data.get('shares_count')} V={strict_data.get('views_count')}")

            return {
                "status": "success",
                "data": strict_data
            }

        except Exception as e:
            self.logger.error(f"FacebookReelScraper failed: {str(e)}", exc_info=True)
            return self.format_error(str(e))
