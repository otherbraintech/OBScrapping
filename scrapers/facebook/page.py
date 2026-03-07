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
        
        get_height_js = "() => (document.scrollingElement || document.body || document.documentElement || {scrollHeight: 0}).scrollHeight"
        
        try:
            last_height = await self.page.evaluate(get_height_js)
        except Exception:
            last_height = 0

        stale_count = 0
        for i in range(count):
            self.logger.info(f"Scrolling ({i+1}/{count})...")
            try:
                scroll_to_js = "window.scrollTo(0, (document.scrollingElement || document.body || document.documentElement || {scrollHeight: 0}).scrollHeight)"
                await self.page.evaluate(scroll_to_js)
                
                await asyncio.sleep(2.5)
                
                new_height = await self.page.evaluate(get_height_js)
                if new_height == last_height or new_height == 0:
                    stale_count += 1
                    await asyncio.sleep(2.0)
                    new_height = await self.page.evaluate(get_height_js)
                    if new_height == last_height:
                        if stale_count >= 2:
                            self.logger.info("Height unchanged after 2 retries, stopping scroll.")
                            break
                        continue
                else:
                    stale_count = 0
                
                last_height = new_height
            except Exception as e:
                self.logger.warning(f"Scroll step {i+1} failed: {e}")
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
            "version": "1.3.4-STABLE",
            "page_info": {},
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
                    
                    await asyncio.sleep(3.0)
                    
                    content_length = await self.page.evaluate("() => document.body ? document.body.innerHTML.length : 0")
                    current_url = self.page.url or ""
                    page_title = await self.page.evaluate("() => document.title || ''")
                    
                    self.logger.info(f"Navigation attempt {attempt+1}: content_length={content_length}, url={current_url}, title={page_title}")
                    
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
            
            self.logger.info("Evaluating JavaScript to extract post containers...")
            posts = await self.page.evaluate(r"""() => {
                const results = [];
                const safeGetText = (e) => {
                    if(!e) return "";
                    try { return (e.innerText || e.textContent || "").trim(); } catch(ex) { return ""; }
                };

                // ============================================================
                // EXTRACT PAGE-LEVEL INFO (name, followers, category)
                // ============================================================
                const pageInfo = {};
                try {
                    const h1 = document.querySelector('h1');
                    if (h1) pageInfo.name = safeGetText(h1);
                    
                    const allText = document.body ? (document.body.innerText || "") : "";
                    const followersMatch = allText.match(/(\d[\d.,]*\s*(?:mil|M|K|millones)?\s*(?:seguidores|followers))/i);
                    if (followersMatch) pageInfo.followers_text = followersMatch[1].trim();
                    
                    const followingMatch = allText.match(/(\d[\d.,]*\s*(?:seguidos|following))/i);
                    if (followingMatch) pageInfo.following_text = followingMatch[1].trim();
                    
                    const catMatch = allText.match(/(Político\(a\)|Musician\/Band|Public Figure|Media\/News Company|Community|Interest|Entertainment Website|Sports Team)/i);
                    if (catMatch) pageInfo.category = catMatch[1];
                    
                    const verifiedBadge = document.querySelector('svg[aria-label*="verificada"], svg[aria-label*="Verified"]');
                    pageInfo.is_verified = !!verifiedBadge;
                } catch(e) {}

                // ============================================================
                // FIND POST LINKS - filter out comments and generic nav links
                // ============================================================
                const contentLinks = document.querySelectorAll(
                    'a[href*="/posts/"], a[href*="/reel/"], a[href*="/videos/"], ' +
                    'a[href*="/permalink/"], a[href*="/story.php"], a[href*="fbid="], ' +
                    'a[href*="/photo"], a[href*="/watch/"]'
                );

                const candidates = new Map();

                contentLinks.forEach(link => {
                    const href = link.href || "";
                    if (!href || href === "#") return;
                    
                    // SKIP comment links - these are not posts
                    if (href.includes('comment_id=')) return;
                    
                    // SKIP generic navigation links (photos tab, videos tab, etc)
                    const genericNav = /\/(photos|videos|about|community|reels|friends|groups|events|mentions|reviews|likes|manage|collections)\/?(\?.*)?$/i;
                    if (genericNav.test(href) && !href.includes('fbid=') && !href.includes('/posts/')) return;

                    // Walk up the DOM to find a meaningful post container
                    let el = link;
                    let bestContainer = null;
                    for (let i = 0; i < 15; i++) {
                        el = el.parentElement;
                        if (!el || el === document.body) break;
                        
                        const role = el.getAttribute('role');
                        if (role === 'banner' || el.tagName === 'HEADER') break;
                        
                        if (role === 'article') {
                            bestContainer = el;
                            break;
                        }
                        
                        const text = safeGetText(el);
                        if (text.length > 80 && el.querySelectorAll('a, img, span').length > 3) {
                            bestContainer = el;
                        }
                    }
                    
                    if (bestContainer && !candidates.has(href)) {
                        candidates.set(href, { element: bestContainer, url: href });
                    }
                });

                // Fallback: role=article
                if (candidates.size === 0) {
                    document.querySelectorAll('div[role="article"]').forEach(article => {
                        let bestLink = null;
                        article.querySelectorAll('a[href]').forEach(a => {
                            const h = a.href || "";
                            if (h.includes('comment_id=')) return;
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
                // EXTRACT DATA from each candidate
                // ============================================================
                candidates.forEach(({ element: container, url: postUrl }) => {
                    const post = { url: postUrl };
                    
                    // Extract post ID
                    const idMatch = postUrl.match(/\/(?:reel|videos|posts|permalink|story\.php|photo|watch)\/([^/?&]+)/) 
                                  || postUrl.match(/fbid=([^&]+)/);
                    if (idMatch) post.id = idMatch[1];

                    // Caption: try specific message containers, then fallback
                    const msgEl = container.querySelector(
                        '[data-ad-comet-preview="post_message"], ' +
                        'div[data-ad-preview="message"], ' +
                        'div[dir="auto"][style]'
                    );
                    if (msgEl) {
                        post.caption = safeGetText(msgEl).substring(0, 500);
                    } else {
                        // Fallback: get text but try to exclude header noise
                        let txt = safeGetText(container);
                        txt = txt.replace(/.*?(?:seguidores|followers).*?(?:Seguir|Follow)\s*/is, '');
                        post.caption = txt.substring(0, 500);
                    }
                    
                    // Raw text for metric extraction in Python
                    post.raw_text = safeGetText(container);
                    
                    // Aria labels (contain reaction/comment/share counts)
                    const ariaLabels = [];
                    container.querySelectorAll('[aria-label]').forEach(el => {
                        const label = el.getAttribute('aria-label');
                        if (label && label.length < 200) ariaLabels.push(label);
                    });
                    post.aria_labels = ariaLabels;

                    // Post date
                    const timeEl = container.querySelector('abbr[data-utime], time, span[id*="jsc_c"]');
                    if (timeEl) {
                        post.post_date_raw = safeGetText(timeEl) || timeEl.getAttribute('title') || timeEl.getAttribute('datetime') || "";
                    }

                    // Thumbnail - filter out profile pics and emojis, pick largest
                    const imgs = Array.from(container.querySelectorAll('img')).filter(img => 
                        img.src && img.src.includes('fbcdn') && 
                        !img.src.includes('emoji') &&
                        (img.width > 100 || img.naturalWidth > 100)
                    );
                    if (imgs.length > 0) {
                        imgs.sort((a, b) => (b.naturalWidth || b.width || 0) - (a.naturalWidth || a.width || 0));
                        post.thumbnail = imgs[0].src;
                    }

                    // Type detection
                    if (postUrl.includes('/reel/') || postUrl.includes('/videos/') || postUrl.includes('/watch/')) {
                        post.type = 'video';
                    } else {
                        post.type = 'post';
                    }

                    results.push(post);
                });

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
                    page_info: pageInfo,
                    _extraction_debug: debugInfo
                };
            }""")

            # ---- PROCESS EXTRACTED POSTS IN PYTHON ----
            raw_result = posts 
            extracted_posts = raw_result.get("posts", [])
            total_candidates = raw_result.get("total_candidates", 0)
            extraction_debug = raw_result.get("_extraction_debug", {})
            page_info = raw_result.get("page_info", {})
            self.logger.info(f"JS Search found {total_candidates} candidates and {len(extracted_posts)} formatted posts.")
            self.logger.info(f"Extraction diagnostics: {extraction_debug}")
            self.logger.info(f"Page info: {page_info}")
            scraped_data["_debug"]["extraction_debug"] = extraction_debug
            scraped_data["page_info"] = page_info
            
            processed_posts = []
            seen_urls = set()

            for p in extracted_posts:
                post_url = p.get("url")
                if not post_url or post_url in seen_urls:
                    continue
                
                # Extra Python-side filter: skip comment links
                if "comment_id=" in post_url:
                    continue
                    
                seen_urls.add(post_url)

                # Use existing utility functions to parse metrics from gathered text
                combined_text = (p.get("raw_text", "") + " " + " ".join(p.get("aria_labels", []))).lower()
                
                views_val = _extract_views_count_from_text(combined_text)
                
                metrics = {
                    "url": post_url,
                    "id": p.get("id"),
                    "type": p.get("type", "post"),
                    "thumbnail": p.get("thumbnail"),
                    "caption": p.get("caption") or p.get("raw_text", "")[:200],
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
