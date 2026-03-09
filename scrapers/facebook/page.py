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

    def _get_extraction_js(self) -> str:
        """Returns the giant JavaScript string used for page extraction."""
        return r"""() => {
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
                // STRATEGY 1 (PRIMARY): Article-based extraction
                // Find div[role="article"] and extract links + data from within each
                // ============================================================
                const articles = document.querySelectorAll('div[role="article"]');
                const candidates = new Map();
                
                console.log("Strategy 1: Found " + articles.length + " article containers");
                
                articles.forEach(article => {
                    // --- NEW FEATURE: Filter out Live Comments and Sidebars ---
                    let p = article.parentElement;
                    let isWithinNoise = false;
                    for (let i = 0; i < 8; i++) {
                        if (!p || p === document.body) break;
                        const role = p.getAttribute('role');
                        const label = (p.getAttribute('aria-label') || "").toLowerCase();
                        if (role === 'complementary' || label.includes('comentarios') || label.includes('comments') || label.includes('chat')) {
                            isWithinNoise = true;
                            break;
                        }
                        p = p.parentElement;
                    }
                    if (isWithinNoise) return;

                    const allLinks = article.querySelectorAll('a[href]');
                    let bestLink = null;
                    
                    allLinks.forEach(a => {
                        const h = a.href || "";
                        if (!h || h === "#") return;
                        if (h.includes('comment_id=')) return;
                        if (/\/(photos|videos|about|community|reels|friends|groups|events|mentions|reviews|likes|manage|collections)\/?(\?.*)?$/i.test(h)) return;
                        
                        if (h.match(/\/(posts|reel|videos|permalink|story\.php|photo|watch)\//i) || h.includes('fbid=')) {
                            if (!bestLink || h.includes('/posts/') || h.includes('/reel/') || h.includes('fbid=')) {
                                bestLink = h;
                            }
                        }
                    });
                    
                    if (bestLink && !candidates.has(bestLink)) {
                        candidates.set(bestLink, { element: article, url: bestLink });
                    }
                });

                // ============================================================
                // STRATEGY 2 (FALLBACK): Link-first approach
                // ============================================================
                if (candidates.size === 0) {
                    console.log("Strategy 1 found nothing. Trying link-first...");
                    const contentLinks = document.querySelectorAll(
                        'a[href*="/posts/"], a[href*="/reel/"], a[href*="/videos/"], ' +
                        'a[href*="/permalink/"], a[href*="/story.php"], a[href*="fbid="], ' +
                        'a[href*="/photo"], a[href*="/watch/"]'
                    );

                    contentLinks.forEach(link => {
                        const href = link.href || "";
                        if (!href || href === "#") return;
                        if (href.includes('comment_id=')) return;
                        
                        const genericNav = /\/(photos|videos|about|community|reels|friends|groups|events|mentions|reviews|likes|manage|collections)\/?(\?.*)?$/i;
                        if (genericNav.test(href) && !href.includes('fbid=') && !href.includes('/posts/')) return;

                        let el = link;
                        let bestContainer = null;
                        for (let i = 0; i < 12; i++) {
                            el = el.parentElement;
                            if (!el || el === document.body) break;
                            
                            const role = el.getAttribute('role');
                            if (role === 'banner' || role === 'navigation' || 
                                role === 'main' || el.tagName === 'HEADER') break;
                            
                            if (role === 'article') {
                                bestContainer = el;
                                break;
                            }
                            
                            const text = safeGetText(el);
                            if (text.length > 50 && text.length < 5000 && 
                                el.querySelectorAll('a, img').length > 2) {
                                bestContainer = el;
                            }
                        }
                        
                        if (bestContainer && !candidates.has(href)) {
                            candidates.set(href, { element: bestContainer, url: href });
                        }
                    });
                }

                candidates.forEach(({ element: container, url: postUrl }) => {
                    const post = { url: postUrl };
                    const idMatch = postUrl.match(/\/(?:reel|videos|posts|permalink|story\.php|photo|watch)\/([^/?&]+)/) 
                                  || postUrl.match(/fbid=([^&]+)/);
                    if (idMatch) post.id = idMatch[1];

                    let captionText = "";
                    const msgSelectors = [
                        '[data-ad-comet-preview="post_message"]',
                        'div[data-ad-preview="message"]',
                        'div[dir="auto"][style*="text-align"]',
                        'div[dir="auto"]'
                    ];
                    
                    for (const sel of msgSelectors) {
                        const els = container.querySelectorAll(sel);
                        for (const el of els) {
                            const txt = safeGetText(el);
                            if (txt.includes("seguidores") && txt.includes("Seguir")) continue;
                            if (txt.includes("Información") && txt.includes("Fotos")) continue;
                            if (txt.length > 10 && txt.length < 2000) {
                                captionText = txt;
                                break;
                            }
                        }
                        if (captionText) break;
                    }
                    
                    post.caption = captionText.substring(0, 500) || "";
                    post.raw_text = safeGetText(container);
                    
                    const ariaLabels = [];
                    container.querySelectorAll('[aria-label]').forEach(el => {
                        const label = el.getAttribute('aria-label');
                        if (label && label.length < 200) ariaLabels.push(label);
                    });
                    post.aria_labels = ariaLabels;

                    const timeEl = container.querySelector('abbr[data-utime], time, span[id*="jsc_c"]');
                    if (timeEl) {
                        post.post_date_raw = safeGetText(timeEl) || timeEl.getAttribute('title') || timeEl.getAttribute('datetime') || "";
                    }

                    const imgs = Array.from(container.querySelectorAll('img[src*="fbcdn"]')).filter(img => {
                        const src = img.src || "";
                        if (src.includes('emoji')) return false;
                        if (src.includes('rsrc.php')) return false;
                        const w = img.width || img.naturalWidth || 0;
                        const h = img.height || img.naturalHeight || 0;
                        return w > 50 || h > 50;
                    });
                    
                    if (imgs.length > 0) {
                        imgs.sort((a, b) => {
                            const aSize = (a.naturalWidth || a.width || 0) * (a.naturalHeight || a.height || 0);
                            const bSize = (b.naturalWidth || b.width || 0) * (b.naturalHeight || b.height || 0);
                            return bSize - aSize;
                        });
                        post.thumbnail = imgs[0].src;
                    }

                    if (postUrl.includes('/reel/') || postUrl.includes('/videos/') || postUrl.includes('/watch/')) {
                        post.type = 'video';
                    } else {
                        post.type = 'post';
                    }

                    results.push(post);
                });

                const debugInfo = {
                    total_links_on_page: document.querySelectorAll('a[href]').length,
                    total_articles: articles.length,
                    has_role_main: document.querySelector('div[role="main"]') !== null,
                    page_title: document.title || "N/A",
                };

                return {
                    posts: results,
                    total_candidates: candidates.size,
                    page_info: pageInfo,
                    _extraction_debug: debugInfo
                };
            }"""

    async def _scroll_page(self, count=10, on_scroll=None):
        """Scroll multiple times to load more posts. Uses progressive delays and
        multiple stale-height retries before giving up."""
        if not self.page:
            return
        
        get_height_js = "() => (document.scrollingElement || document.body || document.documentElement || {scrollHeight: 0}).scrollHeight"
        
        try:
            last_height = await self.page.evaluate(get_height_js)
        except Exception:
            last_height = 0

        stale_count = 0
        for i in range(count):
            self.logger.info(f"Scrolling ({i+1}/{count})... current height={last_height}")
            try:
                # Scroll to bottom
                scroll_to_js = "window.scrollTo(0, (document.scrollingElement || document.body || document.documentElement || {scrollHeight: 0}).scrollHeight)"
                await self.page.evaluate(scroll_to_js)
                
                # Wait for new content to load
                base_wait = 3.5 if i < 5 else 4.5
                await asyncio.sleep(base_wait)
                
                # OPTIONAL: Run callback (e.g. for incremental extraction)
                if on_scroll:
                    try:
                        await on_scroll(i, count)
                    except Exception as cb_err:
                        self.logger.warning(f"On-scroll callback failed: {cb_err}")

                new_height = await self.page.evaluate(get_height_js)
                if new_height == last_height or new_height == 0:
                    stale_count += 1
                    self.logger.info(f"Height stale (attempt {stale_count}/4), waiting extra...")
                    await asyncio.sleep(2.0 + stale_count)
                    await self.page.evaluate("window.scrollBy(0, -300)")
                    await asyncio.sleep(1.0)
                    await self.page.evaluate(scroll_to_js)
                    await asyncio.sleep(2.0)
                    new_height = await self.page.evaluate(get_height_js)
                    if new_height == last_height:
                        if stale_count >= 4:
                            self.logger.info("Height unchanged after 4 retries, stopping scroll.")
                            break
                        continue
                    else:
                        self.logger.info(f"Scroll trick worked! New height: {new_height}")
                        stale_count = 0
                else:
                    stale_count = 0
                
                last_height = new_height
            except Exception as e:
                self.logger.warning(f"Scroll step {i+1} failed: {e}")
                break

    async def run(self, url: str, **kwargs) -> Dict[str, Any]:
        self.logger.info(f"Running FacebookPageScraper for {url}")

        scroll_count: int = kwargs.get("scroll_count", 10)
        extra_wait: float = kwargs.get("extra_wait_seconds", 3.0)
        dump_all: bool = kwargs.get("dump_all", False)

        scraped_data: Dict[str, Any] = {
            "task_id": self.task_id,
            "requested_url": url,
            "scraped_at": datetime.utcnow().isoformat(),
            "content_type": "page_feed",
            "version": "1.5.1-FEED-FIX",
            "page_info": {},
            "posts": [],
            "total_posts_found": 0,
            "_debug": {}
        }

        if not self.page:
            return self.format_error("Browser not initialized", data=scraped_data)

        try:
            await self.inject_cookies()
            self.logger.info(f"Navigating to Page: {url}")
            
            page_loaded = False
            for attempt in range(3):
                try:
                    if attempt == 0:
                        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    elif attempt == 1:
                        await self.page.reload(wait_until="domcontentloaded", timeout=45000)
                    else:
                        await self.page.goto(url, wait_until="load", timeout=60000)
                    
                    await asyncio.sleep(3.0)
                    content_length = await self.page.evaluate("() => document.body ? document.body.innerHTML.length : 0")
                    current_url = self.page.url or ""
                    if "login" in current_url.lower() or "checkpoint" in current_url.lower():
                        break
                    if content_length > 5000:
                        page_loaded = True
                        break
                    await asyncio.sleep(3.0)
                except Exception as nav_err:
                    self.logger.warning(f"Navigation attempt {attempt+1} error: {nav_err}")
                    await asyncio.sleep(2.0)

            if not page_loaded:
                return self.format_error("Page loading failed or blocked.", data=scraped_data)
            
            await self.dismiss_login_banner()
            await asyncio.sleep(max(extra_wait, 5.0))
            
            restriction_msg = await self.check_restricted()
            if restriction_msg:
                return self.format_error(restriction_msg, data=scraped_data)

            # ---- SCROLL TO LOAD DATA (WITH INCREMENTAL EXTRACTION) ----
            extraction_js = self._get_extraction_js()
            all_raw_posts = []
            final_page_info = {}
            final_extraction_debug = {}

            async def on_scroll_callback(current_idx, total_idx):
                self.logger.info(f"Incremental extraction at scroll {current_idx+1}/{total_idx}...")
                try:
                    res = await self.page.evaluate(extraction_js)
                    batch = res.get("posts", [])
                    if batch:
                        self.logger.info(f"Found {len(batch)} posts in this scroll.")
                        all_raw_posts.extend(batch)
                    
                    p_info = res.get("page_info", {})
                    if p_info and not final_page_info.get("name"):
                        final_page_info.update(p_info)
                    final_extraction_debug.update(res.get("_extraction_debug", {}))
                except Exception as ex:
                    self.logger.warning(f"Incremental extraction failed at scroll {current_idx+1}: {ex}")

            await self._scroll_page(scroll_count, on_scroll=on_scroll_callback)

            # Final extraction
            self.logger.info("Performing final extraction...")
            final_res = await self.page.evaluate(extraction_js)
            all_raw_posts.extend(final_res.get("posts", []))
            if not final_page_info.get("name"):
                final_page_info.update(final_res.get("page_info", {}))
            final_extraction_debug.update(final_res.get("_extraction_debug", {}))

            # ---- PROCESS ACCUMULATED POSTS ----
            self.logger.info(f"Accumulated {len(all_raw_posts)} raw posts. Deduplicating and processing...")
            
            scraped_data["page_info"] = final_page_info
            scraped_data["_debug"]["extraction_debug"] = final_extraction_debug
            
            processed_posts = []
            seen_ids = set()

            for p in all_raw_posts:
                post_url = p.get("url")
                post_id = p.get("id")
                if not post_url:
                    continue
                if "comment_id=" in post_url:
                    continue
                
                dedup_key = post_id or post_url
                if dedup_key in seen_ids:
                    continue
                seen_ids.add(dedup_key)

                combined_text = (p.get("raw_text", "") + " " + " ".join(p.get("aria_labels", []))).lower()
                
                metrics = {
                    "url": post_url,
                    "id": post_id,
                    "type": p.get("type", "post"),
                    "thumbnail": p.get("thumbnail"),
                    "caption": p.get("caption") or "",
                    "post_date_raw": p.get("post_date_raw"),
                    "reactions": _extract_reactions_count_from_text(combined_text),
                    "comments": _extract_comments_count_from_text(combined_text),
                    "shares": _extract_shares_count_from_text(combined_text),
                    "views": _extract_views_count_from_text(combined_text),
                }

                for k in ["reactions", "comments", "shares", "views"]:
                    val = metrics.get(k)
                    metrics[f"{k}_count"] = _normalize_count(str(val)) if val else 0

                processed_posts.append(metrics)

            scraped_data["posts"] = processed_posts
            scraped_data["total_posts_found"] = len(processed_posts)
            
            if dump_all:
                scraped_data["_debug"]["full_html"] = await self.page.content()

            if len(processed_posts) == 0:
                scraped_data["_debug"]["full_html"] = await self.page.content()
                return self.format_error("No posts found on the page.", data=scraped_data)

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
            return self.format_error(str(e), data=scraped_data)
