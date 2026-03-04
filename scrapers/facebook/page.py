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

        scraped_data: Dict[str, Any] = {
            "task_id": self.task_id,
            "requested_url": url,
            "scraped_at": datetime.utcnow().isoformat(),
            "content_type": "page_feed",
            "version": "1.1.1",
            "posts": []
        }

        if not self.page:
            return self.format_error("Browser not initialized")

        try:
            # ---- INJECT COOKIES ----
            await self.inject_cookies()

            # ---- NAVIGATE ----
            self.logger.info(f"Navigating to Page: {url}")
            await self.page.goto(url, wait_until="networkidle", timeout=60000)
            # Wait for main content or posts to appear
            self.logger.info("Waiting for page content to load...")
            try:
                await self.page.wait_for_selector('div[role="main"], div[role="article"]', timeout=30000)
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
                // Broadcast logging to console for Playwright to catch if needed
                console.log("Starting container search...");
                
                // Broad search for anything that looks like a post or reel container
                const selectors = [
                    'div[role="article"]',
                    'div[data-pagelet="ProfileTimeline"] [role="main"] > div > div > div',
                    'div[data-testid="post_container"]',
                    'div[style*="aspect-ratio: 0.56"]',
                    'div[style*="aspect-ratio:0.56"]',
                    '.x1yzt60o.x1n2onr6.xh8yej3.x1ja2u2z' // Common classes for grid items
                ];
                
                const containers = document.querySelectorAll(selectors.join(', '));
                console.log(`Found ${containers.length} potential containers`);
                
                containers.forEach((container, index) => {
                    const post = { index };
                    
                    // 1. Try to find a link to the specific post/reel
                    const linkEl = container.querySelector('a[href*="/reel/"], a[href*="/videos/"], a[href*="/posts/"], a[href*="/permalink/"], a[href*="/story.php"]');
                    if (linkEl) {
                        const href = linkEl.href;
                        post.url = href;
                        // Extract ID from URL
                        const m = href.match(/\/(?:reel|videos|posts|permalink|story\.php)\/([^/?]+)/);
                        if (m) post.id = m[1];
                        
                        // 2. Extract Visible Text
                        post.raw_text = container.innerText || "";
                        
                        // 3. Extract aria-labels
                        const ariaLabels = [];
                        container.querySelectorAll('[aria-label]').forEach(el => {
                            ariaLabels.push(el.getAttribute('aria-label'));
                        });
                        post.aria_labels = ariaLabels;

                        // 4. Try to find caption specifically (div with dir="auto")
                        const captionEl = container.querySelector('div[id][dir="auto"], div[data-ad-preview="message"], .x1iorvi4.x17qzfe7.x6ikm8r.x1ot46pu');
                        if (captionEl) {
                            post.caption = captionEl.innerText;
                        }

                        // 5. Try to find post date
                        const dateEl = container.querySelector('span[id*="jsc_c"], a[href*="posts"] span, a[href*="reel"] span > span, span[data-ad-preview="time"]');
                        if (dateEl) {
                          post.post_date_raw = dateEl.innerText;
                        }

                        // 6. Try to find thumbnail
                        const img = container.querySelector('img');
                        if (img) post.thumbnail = img.src;

                        results.push(post);
                    }
                });

                return results;
            }""")

            # ---- PROCESS EXTRACTED POSTS IN PYTHON ----
            processed_posts = []
            for p in posts:
                # Use existing utility functions to parse metrics from gathered text
                combined_text = (p.get("raw_text", "") + " " + " ".join(p.get("aria_labels", []))).lower()
                
                metrics = {
                    "url": p.get("url"),
                    "id": p.get("id"),
                    "thumbnail": p.get("thumbnail"),
                    "caption": p.get("caption") or p.get("raw_text", "")[:200], # Fallback to first 200 chars
                    "post_date_raw": p.get("post_date_raw"),
                    "reactions": _extract_reactions_count_from_text(combined_text),
                    "comments": _extract_comments_count_from_text(combined_text),
                    "shares": _extract_shares_count_from_text(combined_text),
                    "views": _extract_views_count_from_text(combined_text),
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

            self.logger.info(f"Page extraction complete. Found {len(processed_posts)} items.")

            return {
                "status": "success",
                "data": scraped_data
            }

        except Exception as e:
            self.logger.error(f"FacebookPageScraper failed: {str(e)}", exc_info=True)
            return self.format_error(str(e))
