import asyncio
import re
from datetime import datetime
from typing import Dict, Any, List, Optional

from .base import FacebookBaseScraper
from .utils import (
    _normalize_count,
    _extract_views_count_from_text,
    _extract_reactions_count_from_text,
    _extract_comments_count_from_text,
    _extract_shares_count_from_text,
)

class FacebookPageScraper(FacebookBaseScraper):
    """
    Scraper designed to extract metrics from a Facebook Page's Feed or Reels tab.
    It scrolls through the page and captures engagement data for multiple posts/reels.
    """

    async def _scroll_page(self, count=5):
        """Scroll multiple times to load more posts with safety for null body."""
        if not self.page:
            return
        
        # Helper to get the current scroll height safely
        # Using document.scrollingElement as it is the most reliable modern way
        get_height_js = "() => (document.scrollingElement || document.body || document.documentElement || {scrollHeight: 0}).scrollHeight"
        
        try:
            last_height = await self.page.evaluate(get_height_js)
        except Exception:
            last_height = 0

        for i in range(count):
            self.logger.info(f"Scrolling ({i+1}/{count})...")
            try:
                # Use window.scrollTo which is usually more reliable
                scroll_to_js = "window.scrollTo(0, (document.scrollingElement || document.body || document.documentElement || {scrollHeight: 0}).scrollHeight)"
                await self.page.evaluate(scroll_to_js)
                
                # Wait for content to potentially load
                await asyncio.sleep(2.0)
                
                new_height = await self.page.evaluate(get_height_js)
                if new_height == last_height or new_height == 0:
                    # Try one more wait if we might be on a slow load
                    await asyncio.sleep(1.0)
                    new_height = await self.page.evaluate(get_height_js)
                    if new_height == last_height:
                        break
                
                last_height = new_height
            except Exception as e:
                self.logger.warning(f"Scroll step {i+1} failed: {e}")
                # Don't break completely, try next scroll if just a timeout? No, probably a hard failure.
                break

    async def run(self, url: str, **kwargs) -> Dict[str, Any]:
        self.logger.info(f"Running FacebookPageScraper for {url}")

        scroll_count: int = kwargs.get("scroll_count", 5)
        extra_wait: float = kwargs.get("extra_wait_seconds", 3.0)
        dump_all: bool = kwargs.get("dump_all", False)

        scraped_data: Dict[str, Any] = {
            "task_id": self.task_id,
            "requested_url": url,
            "scraped_at": datetime.utcnow().isoformat(),
            "content_type": "page_feed",
            "version": "1.2.5-STABLE-EXPLICIT",
            "posts": [],
            "total_posts_found": 0,
            "_debug": {}
        }

        if not self.page:
            return self.format_error("Browser not initialized")

        try:
            # ---- INJECT COOKIES ----
            await self.inject_cookies()

            # ---- NAVIGATE ----
            self.logger.info(f"Navigating to Page: {url}")
            await self.page.goto(url, wait_until="networkidle", timeout=60000)
            
            # Additional wait for Reels/Videos tabs which are slower
            is_reels = "/reels/" in url.lower() or "/videos/" in url.lower()
            if is_reels:
                self.logger.info("Detected Reels/Videos tab, waiting extra time for grid...")
                await asyncio.sleep(5.0)

            # Wait for main content or posts to appear
            self.logger.info("Waiting for page content to load...")
            try:
                await self.page.wait_for_selector('div[role="main"], div[role="article"], div.x1yzt60o', timeout=30000)
            except Exception:
                self.logger.warning("Main content selectors not found, proceeding with whatever is loaded...")
            
            await asyncio.sleep(max(extra_wait, 3.0))

            # ---- CHECK FOR BLOCKS ----
            restriction_msg = await self.check_restricted()
            if restriction_msg:
                return self.format_error(restriction_msg)

            # ---- SCROLL TO LOAD DATA ----
            await self._scroll_page(scroll_count)

            # ---- EXTRACT POSTS DATA ----
            page_html: str = await self.page.content()
            
            # This JS script finds all post containers and extracts their basic info
            self.logger.info("Evaluating JavaScript to extract post containers...")
            posts = await self.page.evaluate(r"""() => {
                const results = [];
                const safeGetText = (e) => {
                    if(!e) return "";
                    let v = "";
                    try { v = e.innerText || e.textContent || ""; } catch(ex) {}
                    return v.trim();
                };
                console.log("V1.2.0_ULTRA_STABLE_START");
                
                // 1. Broad search for container selectors (modern FB layouts)
                const selectors = [
                    'div[role="article"]',
                    'div[data-pagelet="ProfileTimeline"] [role="main"] > div > div > div',
                    'div[data-testid="post_container"]',
                    'div[style*="aspect-ratio: 0.56"]', // Common for single Reels in grid
                    'div[style*="aspect-ratio:0.56"]',
                    'div.x1yzt60o.x1n2onr6.xh8yej3.x1ja2u2z', // Common grid classes
                    'div.x78zum5.x1q0g3np.x1a2a7bu.x1qugh54', // Reels grid items
                    'div.x1y1zqc1',
                    'div.x1lliihq' // Very generic but useful in some layouts
                ];

                // 2. Build candidates list
                const candidates = new Set();
                selectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => candidates.add(el));
                });

                // 3. Fallback: Search for containers by looking for timestamp/permalink links
                const allLinks = document.querySelectorAll('a[role="link"], a[href*="/reel/"], a[href*="/videos/"], a[href*="/posts/"]');
                allLinks.forEach(a => {
                    const aria = a.getAttribute('aria-label') || '';
                    const innerT = safeGetText(a);
                    const hasTime = /\d/.test(aria) && (
                        /hora|minuto|día|semana|mes|año|hour|minute|day|week|month|year|ago|hace|ayer|yesterday/i.test(aria) ||
                        /\d{1,2}\s*(de\s+)?\w+\s*(de\s+)?\d{4}/i.test(aria) ||
                        innerT.includes(' ') && /\d/.test(innerT)
                    );
                    const isReel = a.href.includes('/reel/') || a.href.includes('/videos/');
                    
                    if (hasTime || isReel) {
                        let parent = a.parentElement;
                        for(let i=0; i<10; i++) {
                            if(!parent) break;
                            const pText = safeGetText(parent);
                            if(pText && pText.length > 50) {
                                candidates.add(parent);
                            }
                            if(parent.getAttribute('role') === 'article') break;
                            parent = parent.parentElement;
                        }
                    }
                });

                console.log(`Analyzing ${candidates.size} candidate containers`);

                // Global views scan to help associate metrics
                const globalText = safeGetText(document.body) || safeGetText(document.documentElement);
                
                Array.from(candidates).forEach((container, index) => {
                    // Skip if container is nested inside another candidate we already processed? 
                    // No, let's keep all for now and deduplicate by URL later.
                    
                    const post = { index };
                    
                    // 1. Link Extraction (URL)
                    const linkEls = Array.from(container.querySelectorAll('a[href]'));
                    const fbLink = linkEls.find(a => 
                        a.href.includes('/reel/') || 
                        a.href.includes('/videos/') || 
                        a.href.includes('/posts/') || 
                        a.href.includes('/permalink/') || 
                        a.href.includes('/story.php') ||
                        a.href.includes('fbid=') ||
                        a.href.includes('/photo')
                    );

                    if (fbLink) {
                        post.url = fbLink.href;
                        const m = post.url.match(/\/(?:reel|videos|posts|permalink|story\.php|photo)\/([^/?]+)/) 
                                || post.url.match(/fbid=([^&]+)/);
                        if (m) post.id = m[1];
                        
                        post.raw_text = safeGetText(container);
                        
                        const ariaLabels = [];
                        container.querySelectorAll('[aria-label]').forEach(el => {
                            ariaLabels.push(el.getAttribute('aria-label'));
                        });
                        post.aria_labels = ariaLabels;

                        // Caption lookup
                        const captionEl = container.querySelector('div[id][dir="auto"], div[data-ad-preview="message"], .x1iorvi4.x17qzfe7.x6ikm8r.x1ot46pu');
                        if (captionEl) post.caption = safeGetText(captionEl);

                        // Date lookup
                        const dateEl = container.querySelector('span[id*="jsc_c"], a[href*="posts"] span, a[href*="reel"] span > span, span[data-ad-preview="time"]');
                        if (dateEl) post.post_date_raw = safeGetText(dateEl);

                        // Thumbnail
                        const imgs = Array.from(container.querySelectorAll('img')).filter(img => 
                            img.src.includes('fbcdn') && !img.src.includes('profile')
                        );
                        if (imgs.length > 0) post.thumbnail = imgs[0].src;

                        // Type detection
                        if (post.url.includes('/reel/') || post.url.includes('/videos/')) {
                            post.type = 'video';
                        } else {
                            post.type = 'post';
                        }

                        results.push(post);
                    }
                });

                return {
                    posts: results,
                    total_candidates: candidates.size
                };
            }""")

            # ---- PROCESS EXTRACTED POSTS IN PYTHON ----
            raw_result = posts 
            extracted_posts = raw_result.get("posts", [])
            total_candidates = raw_result.get("total_candidates", 0)
            self.logger.info(f"JS Search found {total_candidates} candidates and {len(extracted_posts)} formatted posts.")
            
            processed_posts = []
            seen_urls = set()

            for p in extracted_posts:
                post_url = p.get("url")
                if not post_url or post_url in seen_urls:
                    continue
                seen_urls.add(post_url)

                # Use existing utility functions to parse metrics from gathered text
                combined_text = (p.get("raw_text", "") + " " + " ".join(p.get("aria_labels", []))).lower()
                
                # Check for views in this specific post's text
                views_val = _extract_views_count_from_text(combined_text)
                
                metrics = {
                    "url": post_url,
                    "id": p.get("id"),
                    "type": p.get("type", "post"),
                    "thumbnail": p.get("thumbnail"),
                    "caption": p.get("caption") or p.get("raw_text", "")[:200], # Fallback
                    "post_date_raw": p.get("post_date_raw"),
                    "reactions": _extract_reactions_count_from_text(combined_text),
                    "comments": _extract_comments_count_from_text(combined_text),
                    "shares": _extract_shares_count_from_text(combined_text),
                    "views": views_val,
                }

                # Normalize counts
                for k in ["reactions", "comments", "shares", "views"]:
                    val = metrics.get(k)
                    if val:
                        metrics[f"{k}_count"] = _normalize_count(str(val))
                    else:
                        metrics[f"{k}_count"] = 0

                processed_posts.append(metrics)

            scraped_data["posts"] = processed_posts
            scraped_data["total_posts_found"] = len(processed_posts)
            scraped_data["_debug"]["total_candidates"] = total_candidates
            
            if dump_all:
                scraped_data["_debug"]["full_html"] = await self.page.content()

            if len(processed_posts) == 0:
                self.logger.warning(f"No posts found for {url}. Dumping HTML to _debug.")
                scraped_data["_debug"]["full_html"] = await self.page.content()
            else:
                self.logger.info(f"Page extraction successful. Found {len(processed_posts)} unique items.")

            return {
                "status": "success",
                "data": {
                    **scraped_data,
                    "final_url": self.page.url if self.page else url
                }
            }

        except Exception as e:
            self.logger.error(f"FacebookPageScraper failed: {str(e)}", exc_info=True)
            # DUMP HTML FOR ANALYSIS if it fails or returns 0
            try:
                html = await self.page.content()
                from pathlib import Path
                dump_path = Path("docs") / f"last_failed_scrape_{self.task_id}.html"
                dump_path.parent.mkdir(exist_ok=True)
                dump_path.write_text(html, encoding="utf-8")
                self.logger.info(f"Raw HTML dumped to {dump_path}")
            except:
                pass
            return self.format_error(str(e))
