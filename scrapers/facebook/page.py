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
        """Scroll multiple times to load more posts."""
        if not self.page:
            return
        last_height = await self.page.evaluate("document.body.scrollHeight")
        for i in range(count):
            self.logger.info(f"Scrolling ({i+1}/{count})...")
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2.0)
            new_height = await self.page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    async def run(self, url: str, **kwargs) -> Dict[str, Any]:
        self.logger.info(f"Running FacebookPageScraper for {url}")

        scroll_count: int = kwargs.get("scroll_count", 5)
        extra_wait: float = kwargs.get("extra_wait_seconds", 3.0)

        scraped_data: Dict[str, Any] = {
            "task_id": self.task_id,
            "requested_url": url,
            "scraped_at": datetime.utcnow().isoformat(),
            "content_type": "page_feed",
            "version": "1.1.0",
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
            posts = await self.page.evaluate(r"""() => {
                const results = [];
                // Find all potential post/reel containers
                // 1. Grid Reels (aspect ratio ~0.56)
                // 2. Feed Posts (role="article")
                const containers = document.querySelectorAll('div[role="article"], div[data-pagelet="ProfileTimeline"] div[role="main"] > div > div > div, div[style*="aspect-ratio: 0.56"], div[style*="aspect-ratio:0.56"]');
                
                containers.forEach((container, index) => {
                    const post = { index };
                    
                    // 1. Try to find a link to the specific post/reel
                    const linkEl = container.querySelector('a[href*="/reel/"], a[href*="/videos/"], a[href*="/posts/"], a[href*="/permalink/"]');
                    if (linkEl) {
                        const href = linkEl.href;
                        post.url = href;
                        // Extract ID from URL
                        const m = href.match(/\/(?:reel|videos|posts|permalink)\/([^/?]+)/);
                        if (m) post.id = m[1];
                        
                        // 2. Extract visible text (metrics usually appear here)
                        const text = container.innerText || "";
                        post.raw_text = text.substring(0, 500);
                        
                        // 3. Extract aria-labels
                        const ariaLabels = [];
                        container.querySelectorAll('[aria-label]').forEach(el => {
                            ariaLabels.push(el.getAttribute('aria-label'));
                        });
                        post.aria_labels = ariaLabels;

                        // 4. Try to find thumbnail
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
