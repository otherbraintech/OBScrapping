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
            "version": "1.3.2-COOKIES",
            "posts": [],
            "total_posts_found": 0,
            "_debug": {}
        }

        if not self.page:
            return self.format_error("Browser not initialized", data=scraped_data)

        try:
            # ---- INJECT COOKIES ----
            await self.inject_cookies()

            # ---- NAVIGATE WITH RESILIENT STRATEGY ----
            self.logger.info(f"Navigating to Page: {url}")
            
            # Attempt 1: Standard navigation
            page_loaded = False
            for attempt in range(3):
                try:
                    if attempt == 0:
                        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    elif attempt == 1:
                        self.logger.warning("Attempt 1 failed or empty. Retrying with reload...")
                        await self.page.reload(wait_until="domcontentloaded", timeout=45000)
                    else:
                        self.logger.warning("Attempt 2 failed. Trying with load wait...")
                        await self.page.goto(url, wait_until="load", timeout=60000)
                    
                    # Brief wait for dynamic content
                    await asyncio.sleep(3.0)
                    
                    # Check if page has meaningful content
                    content_length = await self.page.evaluate("() => document.body ? document.body.innerHTML.length : 0")
                    current_url = self.page.url or ""
                    page_title = await self.page.evaluate("() => document.title || ''")
                    
                    self.logger.info(f"Navigation attempt {attempt+1}: content_length={content_length}, url={current_url}, title={page_title}")
                    
                    # Check for login redirect
                    if "login" in current_url.lower() or "checkpoint" in current_url.lower():
                        self.logger.warning(f"Redirected to login/checkpoint: {current_url}")
                        scraped_data["_debug"]["redirect_detected"] = current_url
                        break
                    
                    if content_length > 5000:
                        page_loaded = True
                        self.logger.info(f"Page loaded successfully on attempt {attempt+1}")
                        break
                    else:
                        self.logger.warning(f"Page seems empty on attempt {attempt+1} ({content_length} bytes)")
                        await asyncio.sleep(3.0)
                        
                except Exception as nav_err:
                    self.logger.warning(f"Navigation attempt {attempt+1} error: {nav_err}")
                    await asyncio.sleep(2.0)

            # Capture pre-extraction diagnostics
            pre_check = await self.page.evaluate(r"""() => {
                return {
                    url: window.location.href,
                    title: document.title,
                    body_length: document.body ? document.body.innerHTML.length : 0,
                    body_text_length: document.body ? (document.body.innerText || '').length : 0,
                    has_role_main: !!document.querySelector('div[role="main"]'),
                    has_articles: document.querySelectorAll('div[role="article"]').length,
                    total_links: document.querySelectorAll('a[href]').length,
                    total_images: document.querySelectorAll('img').length,
                    has_login_form: !!document.querySelector('form[action*="login"]'),
                    fb_content_links: document.querySelectorAll('a[href*="/posts/"], a[href*="/reel/"], a[href*="/videos/"]').length,
                };
            }""")
            self.logger.info(f"Pre-extraction diagnostics: {pre_check}")
            scraped_data["_debug"]["pre_check"] = pre_check

            if not page_loaded:
                body_length = pre_check.get("body_length", 0)
                if body_length < 1000:
                    scraped_data["_debug"]["full_html"] = await self.page.content()
                    return self.format_error(
                        f"Facebook returned an empty or minimal page ({body_length} bytes). "
                        f"This usually means: (1) cookies expired, (2) IP is blocked, or (3) the page requires login. "
                        f"Current URL: {pre_check.get('url', 'unknown')}. Title: {pre_check.get('title', 'unknown')}.",
                        data=scraped_data
                    )
            
            # ---- DISMISS LOGIN POPUPS ----
            await self.dismiss_login_banner()

            # Additional wait for Reels/Videos tabs which are slower
            is_reels = "/reels/" in url.lower() or "/videos/" in url.lower()
            if is_reels:
                self.logger.info("Detected Reels/Videos tab, waiting extra time for grid...")
                await asyncio.sleep(5.0)

            # Wait for main content to appear (soft wait)
            self.logger.info("Waiting for page content selectors...")
            try:
                await self.page.wait_for_selector('div[role="main"], div[role="article"], a[href*="/posts/"], a[href*="/reel/"]', timeout=15000)
            except Exception:
                self.logger.warning("Content selectors not found within timeout, proceeding anyway...")
            
            await asyncio.sleep(max(extra_wait, 3.0))

            # ---- CHECK FOR BLOCKS ----
            restriction_msg = await self.check_restricted()
            if restriction_msg:
                return self.format_error(restriction_msg, data=scraped_data)

            # ---- SCROLL TO LOAD DATA ----
            await self._scroll_page(scroll_count)

            # ---- EXTRACT POSTS DATA ----
            page_html: str = await self.page.content()
            self.logger.info(f"Page content captured. Length: {len(page_html)} characters.")
            
            # This JS script finds all post containers and extracts their basic info
            self.logger.info("Evaluating JavaScript to extract post containers...")
            posts = await self.page.evaluate(r"""() => {
                const results = [];
                const safeGetText = (e) => {
                    if(!e) return "";
                    try { return (e.innerText || e.textContent || "").trim(); } catch(ex) { return ""; }
                };
                console.log("V1.3.0_RESILIENT_EXTRACTION_START");

                // ============================================================
                // STRATEGY 1: Link-first approach (most resilient)
                // Find all links that point to FB content, then walk up to container
                // ============================================================
                const contentLinks = document.querySelectorAll(
                    'a[href*="/posts/"], a[href*="/reel/"], a[href*="/videos/"], ' +
                    'a[href*="/permalink/"], a[href*="/story.php"], a[href*="fbid="], ' +
                    'a[href*="/photo"], a[href*="/watch/"]'
                );
                console.log(`Found ${contentLinks.length} content links on page`);

                const candidates = new Map(); // url -> container element

                contentLinks.forEach(link => {
                    const href = link.href || "";
                    if (!href || href === "#") return;
                    
                    // FILTER: Ignore common navigation links that aren't specific posts/media
                    // Regex handles trailing slashes and query params robustly
                    const genericUrlRegex = /\/(photos|videos|about|community|reels|friends|groups|events|mentions|reviews|map|sports|music|movies|books|likes|manage|collections)\/?(\?.*)?$/i;
                    
                    if (genericUrlRegex.test(href) && !href.includes('fbid=') && !href.includes('/posts/')) {
                        return;
                    }

                    // Walk up the DOM to find a meaningful container
                    let el = link;
                    let bestContainer = null;
                    for (let i = 0; i < 15; i++) {
                        el = el.parentElement;
                        if (!el || el === document.body) break;
                        
                        // SKIP: If we hit a container with profile header keywords, top - this isn't a post
                        const text = safeGetText(el);
                        if (text.includes("Seguidores") || text.includes("Mensaje") || text.includes("Seguir") || text.includes(" Político(a)")) {
                             break;
                        }

                        if (role === 'article') {
                            bestContainer = el;
                            break;
                        }
                        
                        // Heuristic for a container: enough text and some children
                        if (text.length > 80 && el.querySelectorAll('a, img, span').length > 3) {
                            bestContainer = el;
                        }
                    }
                    
                    if (bestContainer && !candidates.has(href)) {
                        candidates.set(href, { element: bestContainer, url: href });
                    }
                });

                // ============================================================
                // STRATEGY 2: Role-based fallback
                // ============================================================
                if (candidates.size === 0) {
                    console.log("Strategy 1 found nothing. Trying role=article...");
                    document.querySelectorAll('div[role="article"]').forEach(article => {
                        const links = article.querySelectorAll('a[href]');
                        let bestLink = null;
                        links.forEach(a => {
                            const h = a.href || "";
                            if (h.match(/\/(posts|reel|videos|permalink|story\.php|photo|watch)\//i) || h.includes('fbid=')) {
                                bestLink = h;
                            }
                        });
                        if (bestLink && !candidates.has(bestLink)) {
                            candidates.set(bestLink, { element: article, url: bestLink });
                        }
                    });
                }

                // ============================================================
                // STRATEGY 3: Pagelet-based fallback
                // ============================================================
                if (candidates.size === 0) {
                    console.log("Strategy 2 found nothing. Trying data-pagelet...");
                    const pagelets = document.querySelectorAll(
                        'div[data-pagelet*="ProfileTimeline"], div[data-pagelet*="Feed"], ' +
                        'div[data-pagelet*="Page"], div[role="main"]'
                    );
                    pagelets.forEach(pagelet => {
                        pagelet.querySelectorAll('a[href]').forEach(link => {
                            const h = link.href || "";
                            if (h.match(/\/(posts|reel|videos|permalink|photo|watch)\//i) || h.includes('fbid=')) {
                                if (!candidates.has(h)) {
                                    let parent = link;
                                    for (let i = 0; i < 8; i++) {
                                        parent = parent.parentElement;
                                        if (!parent) break;
                                        if (safeGetText(parent).length > 50) {
                                            candidates.set(h, { element: parent, url: h });
                                            break;
                                        }
                                    }
                                }
                            }
                        });
                    });
                }

                console.log(`Total unique candidates: ${candidates.size}`);

                // ============================================================
                // EXTRACT DATA from each candidate
                // ============================================================
                candidates.forEach(({ element: container, url: postUrl }) => {
                    const post = { url: postUrl };
                    
                    const idMatch = postUrl.match(/\/(?:reel|videos|posts|permalink|story\.php|photo|watch)\/([^/?&]+)/) 
                                  || postUrl.match(/fbid=([^&]+)/);
                    if (idMatch) post.id = idMatch[1];
                    // Specific targeting for caption to avoid metadata noise
                    const captionEl = container.querySelector('[data-ad-comet-preview="post_message"]');
                    post.caption = captionEl ? safeGetText(captionEl) : safeGetText(container).substring(0, 500);
                    
                    const reactionsEl = container.querySelector('span[role="toolbar"]'); // This line was added, but not used in the snippet. Keeping it as is.
                    const ariaLabels = [];
                    container.querySelectorAll('[aria-label]').forEach(el => {
                        const label = el.getAttribute('aria-label');
                        if (label && label.length < 200) ariaLabels.push(label);
                    });
                    post.aria_labels = ariaLabels;

                    const captionEl = container.querySelector(
                        'div[id][dir="auto"], div[data-ad-preview="message"], div[dir="auto"][style*="text-align"]'
                    );
                    if (captionEl) post.caption = safeGetText(captionEl);

                    const timeEl = container.querySelector('abbr[data-utime], time, span[id*="jsc_c"]');
                    if (timeEl) {
                        post.post_date_raw = safeGetText(timeEl) || timeEl.getAttribute('title') || timeEl.getAttribute('datetime') || "";
                    }

                    const imgs = Array.from(container.querySelectorAll('img')).filter(img => 
                        img.src && img.src.includes('fbcdn') && 
                        !img.src.includes('profile') && !img.src.includes('emoji') &&
                        (img.width > 50 || img.naturalWidth > 50)
                    );
                    if (imgs.length > 0) post.thumbnail = imgs[0].src;

                    if (postUrl.includes('/reel/') || postUrl.includes('/videos/') || postUrl.includes('/watch/')) {
                        post.type = 'video';
                    } else {
                        post.type = 'post';
                    }

                    results.push(post);
                });

                // Diagnostic info
                const debugInfo = {
                    total_links_on_page: document.querySelectorAll('a[href]').length,
                    total_divs: document.querySelectorAll('div').length,
                    has_role_main: document.querySelector('div[role="main"]') !== null,
                    has_role_article: document.querySelectorAll('div[role="article"]').length,
                    page_title: document.title || "N/A",
                    body_text_length: (document.body ? document.body.innerText || "" : "").length,
                };

                return {
                    posts: results,
                    total_candidates: candidates.size,
                    _extraction_debug: debugInfo
                };
            }""")

            # ---- PROCESS EXTRACTED POSTS IN PYTHON ----
            raw_result = posts 
            extracted_posts = raw_result.get("posts", [])
            total_candidates = raw_result.get("total_candidates", 0)
            extraction_debug = raw_result.get("_extraction_debug", {})
            self.logger.info(f"JS Search found {total_candidates} candidates and {len(extracted_posts)} formatted posts.")
            self.logger.info(f"Extraction diagnostics: {extraction_debug}")
            scraped_data["_debug"]["extraction_debug"] = extraction_debug
            
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
                return self.format_error(f"No posts found on the page. HTML size: {len(scraped_data['_debug']['full_html'])} bytes.", data=scraped_data)

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
            return self.format_error(str(e), data=scraped_data)
