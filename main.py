import asyncio
import logging
import random
import uuid
import os
from datetime import datetime
from typing import Optional, Dict, Any, List
import re
from dotenv import load_dotenv

load_dotenv()

import httpx
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_async

# --- Configuration ---
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
if not WEBHOOK_URL:
    logging.warning("WEBHOOK_URL not set. App will run but webhook notifications will be skipped.")
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
]
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 720}
]

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("fb_scraper")
logger.setLevel(logging.INFO)

# --- Models ---
class ScrapeRequest(BaseModel):
    url: HttpUrl
    network: Optional[str] = "facebook"
    type: Optional[str] = "reel"

class ScrapeTaskResponse(BaseModel):
    status: str
    task_id: str
    message: str

# --- Helper Functions ---
class TaskLogger(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[{self.extra.get('task_id', 'unknown')}] {msg}", kwargs

def get_random_delay(min_seconds=10.0, max_seconds=30.0):
    return random.uniform(min_seconds, max_seconds)

async def simulate_human_behavior(page, task_logger):
    """Simulates scrolling and mouse movements to load dynamic content."""
    task_logger.info("Simulating human behavior (scrolling)...")

    # Mouse movement
    try:
        await page.mouse.move(random.randint(100, 500), random.randint(100, 500))
        await asyncio.sleep(random.uniform(1.0, 2.0))
    except Exception as e:
        task_logger.warning(f"Mouse move failed: {e}")

    # Scroll down gradually to trigger lazy loading of engagement section
    try:
        # First scroll slowly through the page
        for i in range(5):
            await page.evaluate(f"window.scrollBy(0, {300 + i * 100})")
            await asyncio.sleep(random.uniform(1.5, 3.0))
        
        # Scroll to bottom
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(3)
        
        # Scroll back up to the engagement section area
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(2)
        await page.evaluate("window.scrollBy(0, 600)")
        await asyncio.sleep(3)
    except Exception as e:
        task_logger.warning(f"Scroll failed: {e}")
    
    # Try to close any login popup/overlay that might block content
    try:
        close_selectors = [
            "div[aria-label='Close']", "div[aria-label='Cerrar']",
            "[aria-label='Close']", "[aria-label='Cerrar']",
            "i.x1b0d499",  # Facebook close icon class
        ]
        for sel in close_selectors:
            btn = page.locator(sel)
            if await btn.count() > 0:
                task_logger.info(f"Found close button ({sel}), clicking...")
                await btn.first.click()
                await asyncio.sleep(2)
                break
    except:
        pass

async def send_webhook(data: Dict[str, Any], task_logger):
    """Sends the result to the n8n webhook."""
    if not WEBHOOK_URL:
        task_logger.warning("WEBHOOK_URL not configured, skipping webhook.")
        return
    task_logger.info(f"Sending webhook to {WEBHOOK_URL}...")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(WEBHOOK_URL, json=data)
            response.raise_for_status()
            task_logger.info(f"Webhook sent successfully: {response.status_code}")
        except httpx.HTTPError as e:
            task_logger.error(f"Webhook failed: {e}")

# --- Core Scraper ---
async def run_scraper(task_id: str, url: str):
    task_logger = TaskLogger(logger, {"task_id": task_id})
    task_logger.info(f"Starting scrape for URL: {url}")

    result = {
        "task_id": task_id,
        "url": url,
        "status": "pending",
        "scraped_at": datetime.utcnow().isoformat(),
        "data": {},
        "error": None
    }

    playwright = None
    browser = None
    context = None
    page = None

    try:
        playwright = await async_playwright().start()
        
        # Launch browser
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )

        # Setup context with random parameters
        user_agent = random.choice(USER_AGENTS)
        viewport = random.choice(VIEWPORTS)
        
        task_logger.info(f"Using UA: {user_agent[:50]}... Viewport: {viewport}")

        # Proxy configuration (if provided)
        proxy_config = None
        proxy_host = os.getenv("PROXY_HOST")
        proxy_port = os.getenv("PROXY_PORT")
        proxy_user = os.getenv("PROXY_USERNAME")
        proxy_pass = os.getenv("PROXY_PASSWORD")
        
        if proxy_host and proxy_port:
            proxy_config = {
                "server": f"http://{proxy_host}:{proxy_port}",
            }
            if proxy_user and proxy_pass:
                proxy_config["username"] = proxy_user
                proxy_config["password"] = proxy_pass
            task_logger.info(f"Using proxy: {proxy_host}:{proxy_port}")
        else:
            task_logger.warning("No proxy configured - may be blocked by Cloudflare")

        context = await browser.new_context(
            user_agent=user_agent,
            viewport=viewport,
            proxy=proxy_config,
            locale="en-US",
            timezone_id="America/New_York",
            device_scale_factor=random.choice([1, 1.5, 2]),
            has_touch=random.choice([True, False]),
            is_mobile=False # Desktop simulation usually better for stealth than mobile
        )

        page = await context.new_page()

        # Apply stealth
        await stealth_async(page)
        
        # Inject Facebook cookies if provided (works with proxy for logged-in access)
        fb_c_user = os.getenv("FB_COOKIE_C_USER")
        fb_xs = os.getenv("FB_COOKIE_XS")
        fb_datr = os.getenv("FB_COOKIE_DATR")  # Critical for device fingerprinting
        fb_fr = os.getenv("FB_COOKIE_FR")      # Facebook request token
        fb_sb = os.getenv("FB_COOKIE_SB")      # Secure browsing token
        
        if fb_c_user and fb_xs:
            task_logger.info("Facebook cookies found, injecting into browser context...")
            cookies = [
                {
                    "name": "c_user",
                    "value": fb_c_user,
                    "domain": ".facebook.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                    "sameSite": "None"
                },
                {
                    "name": "xs",
                    "value": fb_xs,
                    "domain": ".facebook.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None"
                }
            ]
            
            # Add optional but important cookies
            if fb_datr:
                cookies.append({
                    "name": "datr",
                    "value": fb_datr,
                    "domain": ".facebook.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None"
                })
            if fb_fr:
                cookies.append({
                    "name": "fr",
                    "value": fb_fr,
                    "domain": ".facebook.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None"
                })
            if fb_sb:
                cookies.append({
                    "name": "sb",
                    "value": fb_sb,
                    "domain": ".facebook.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None"
                })
            
            await context.add_cookies(cookies)
            task_logger.info(f"Injected {len(cookies)} Facebook cookies successfully.")
        else:
            task_logger.warning("No Facebook cookies configured. Scraping as anonymous user (limited data).")
        
        # Navigate
        task_logger.info("Navigating to page...")
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
        except PlaywrightTimeoutError:
             task_logger.warning("Navigation timed out, trying to proceed anyway...")

        # Initial random wait
        await asyncio.sleep(get_random_delay(5, 10))

        # Check for blocking/login wall
        content = await page.content()
        content_lower = content.lower()
        
        # Basic checks for login walls or blocks
        login_keywords = ["log in to facebook", "inicia sesión", "sign up", "registrarse", "security check", "captcha"]
        # Check against title and common login indicators
        title = await page.title()
        
        is_login_wall = (
            any(k in title.lower() for k in login_keywords) or 
            len(content) < 2000 # Suspiciously short content
        )

        # Try to detect explicit login container if keywords match
        # (Be careful not to false positive on 'Log in' button in header)
        # Often login walls are modal dialogs or redirect to login pages
        if "login.php" in page.url or "checkpoint" in page.url:
            is_login_wall = True

        if is_login_wall:
             # Double check if we can see content behind it (sometimes it's just a bottom banner)
             # Try to find the close button for the login banner.
             try:
                 close_button = page.locator("div[aria-label='Close'], div[aria-label='Cerrar']")
                 if await close_button.count() > 0:
                     task_logger.info("Found login banner close button, attempting to close...")
                     await close_button.first.click()
                     await asyncio.sleep(2)
                     is_login_wall = False # Recovered
             except:
                 pass

        if is_login_wall:
            task_logger.error("Detected login wall or block.")
            result["status"] = "error"
            result["error"] = "blocked_or_login_wall"
            await send_webhook(result, task_logger)
            return

        # Simulate behavior to load more content/comments/reactions
        await simulate_human_behavior(page, task_logger)

        # ===== DIAGNOSTIC: Capture what Facebook is showing =====
        try:
            current_url = page.url
            current_title = await page.title()
            page_html = await page.content()
            
            task_logger.info(f"DIAGNOSTIC - Final URL: {current_url}")
            task_logger.info(f"DIAGNOSTIC - Page Title: {current_title}")
            task_logger.info(f"DIAGNOSTIC - HTML Length: {len(page_html)} bytes")
            
            # Save screenshot for debugging
            screenshot_path = f"/tmp/fb_debug_{task_id[:8]}.png"
            await page.screenshot(path=screenshot_path, full_page=False)
            task_logger.info(f"DIAGNOSTIC - Screenshot saved: {screenshot_path}")
            
            # Log HTML preview (first 1000 chars)
            task_logger.info(f"DIAGNOSTIC - HTML Preview: {page_html[:1000]}")
            
            # Check for common blocking patterns
            if "checkpoint" in current_url.lower():
                task_logger.error("Facebook redirected to security checkpoint - cookies may be invalid or flagged")
            if "login" in current_url.lower():
                task_logger.error("Facebook redirected to login page - cookies expired or invalid")
            if len(page_html) < 5000:
                task_logger.warning(f"Very short HTML ({len(page_html)} bytes) - possible block or error page")
        except Exception as diag_err:
            task_logger.warning(f"Diagnostic logging failed: {diag_err}")

        # ===== PARSING LOGIC =====
        task_logger.info("Parsing page content...")
        scraped_data = {}

        # --- LAYER 1: OG Meta Tags (most reliable) ---
        task_logger.info("Extracting OG meta tags...")
        og_tags = [
            "og:title", "og:description", "og:image", "og:url",
            "og:video", "og:video:url", "og:video:secure_url",
            "og:video:type", "og:video:width", "og:video:height",
            "og:type", "og:site_name"
        ]
        og_found_count = 0
        for tag in og_tags:
            try:
                el = page.locator(f'meta[property="{tag}"]')
                if await el.count() > 0:
                    value = await el.first.get_attribute("content")
                    key = tag.replace(":", "_").replace(".", "_")
                    scraped_data[key] = value
                    og_found_count += 1
                    task_logger.info(f"Found OG tag {tag}: {value[:100]}...")
            except Exception as e:
                task_logger.warning(f"Error reading {tag}: {e}")
        
        task_logger.info(f"Found {og_found_count} OG meta tags total")

        # Also grab standard meta description
        try:
            meta_desc = page.locator('meta[name="description"]')
            if await meta_desc.count() > 0:
                scraped_data["meta_description"] = await meta_desc.first.get_attribute("content")
        except:
            pass

        # --- LAYER 2: Page title ---
        try:
            scraped_data["page_title"] = await page.title()
        except:
            pass

        # --- LAYER 3: Parse OG title for engagement data ---
        # Facebook OG titles often contain: "291 reactions · 38 shares | Caption text | Author Name"
        og_title = scraped_data.get("og_title", "")
        if og_title:
            task_logger.info(f"Parsing OG title: {og_title[:100]}...")
            
            # Extract reactions from OG title
            og_reactions_match = re.search(r'([\d,.]+[KMkm]?)\s*(?:reactions?|reacciones)', og_title, re.IGNORECASE)
            if og_reactions_match:
                scraped_data["reactions"] = og_reactions_match.group(1)
            
            # Extract shares from OG title
            og_shares_match = re.search(r'([\d,.]+[KMkm]?)\s*(?:shares?|compartido|veces compartido)', og_title, re.IGNORECASE)
            if og_shares_match:
                scraped_data["shares"] = og_shares_match.group(1)
            
            # Extract comments from OG title
            og_comments_match = re.search(r'([\d,.]+[KMkm]?)\s*(?:comments?|comentarios)', og_title, re.IGNORECASE)
            if og_comments_match:
                scraped_data["comments"] = og_comments_match.group(1)

            # Extract views from OG title
            og_views_match = re.search(r'([\d,.]+[KMkm]?)\s*(?:views?|visualizaciones|reproducciones)', og_title, re.IGNORECASE)
            if og_views_match:
                scraped_data["views"] = og_views_match.group(1)

            # Extract author from OG title (usually after last "|")
            if "|" in og_title:
                parts = og_title.split("|")
                # Author is typically the last part
                potential_author = parts[-1].strip()
                if potential_author and len(potential_author) > 1 and len(potential_author) < 100:
                    scraped_data["author_from_title"] = potential_author
                # Clean caption is the middle part (between engagement stats and author)
                if len(parts) >= 3:
                    scraped_data["clean_caption"] = parts[1].strip()
                elif len(parts) == 2:
                    scraped_data["clean_caption"] = parts[0].strip()
                    # Remove the engagement prefix if present
                    caption = scraped_data["clean_caption"]
                    caption = re.sub(r'^[\d,.]+[KMkm]?\s*(?:reactions?|reacciones)\s*·?\s*', '', caption, flags=re.IGNORECASE)
                    caption = re.sub(r'^[\d,.]+[KMkm]?\s*(?:shares?|compartido)\s*·?\s*', '', caption, flags=re.IGNORECASE)
                    scraped_data["clean_caption"] = caption.strip()

        # --- LAYER 4: JavaScript evaluation for deep data extraction ---
        task_logger.info("Running JavaScript extraction...")
        try:
            js_data = await page.evaluate("""() => {
                const data = {};
                
                // Scan all aria-labels
                const allElements = document.querySelectorAll('[aria-label]');
                const ariaLabels = [];
                allElements.forEach(el => {
                    const label = el.getAttribute('aria-label');
                    if (label) ariaLabels.push(label);
                });
                data.aria_labels = ariaLabels;
                
                // Find ALL span texts that contain numbers (broad capture)
                const engagementTexts = [];
                const allSpans = document.querySelectorAll('span');
                allSpans.forEach(span => {
                    const text = span.innerText.trim();
                    if (text && text.length < 150 && text.length > 0) {
                        if (/\d/.test(text)) {
                            engagementTexts.push(text);
                        }
                    }
                });
                data.engagement_texts = engagementTexts;
                
                // Find ALL div texts with "Todas las reacciones" or reaction counts
                const reactionDivs = document.querySelectorAll('div[role="button"]');
                const buttonTexts = [];
                reactionDivs.forEach(div => {
                    const text = div.innerText.trim();
                    if (text && text.length < 100) {
                        buttonTexts.push(text);
                    }
                });
                data.button_texts = buttonTexts;
                
                // Find video duration if available
                const video = document.querySelector('video');
                if (video) {
                    data.video_duration = video.duration || null;
                    data.video_src = video.src || null;
                    data.video_poster = video.poster || null;
                }
                
                // Find timestamp/date
                const timeLinks = document.querySelectorAll('a[role="link"]');
                timeLinks.forEach(link => {
                    const ariaLabel = link.getAttribute('aria-label');
                    if (ariaLabel && /\d/.test(ariaLabel) && (
                        /hora|minuto|día|semana|mes|año|hour|minute|day|week|month|year|ago|hace|ayer|yesterday/i.test(ariaLabel) ||
                        /\d{1,2}\s*(de\s+)?\w+\s*(de\s+)?\d{4}/i.test(ariaLabel)
                    )) {
                        data.post_date = ariaLabel;
                    }
                });
                
                // Find all abbr/time elements
                const timeEls = document.querySelectorAll('abbr, time');
                timeEls.forEach(el => {
                    const title = el.getAttribute('title') || el.getAttribute('datetime');
                    if (title) {
                        data.post_date = data.post_date || title;
                    }
                });
                
                return data;
            }""")
            
            task_logger.info(f"JS extraction found: {len(js_data.get('aria_labels', []))} aria-labels, {len(js_data.get('engagement_texts', []))} engagement texts, {len(js_data.get('button_texts', []))} button texts")
            
            # DEBUG: Log what we actually found for diagnosis
            for label in js_data.get("aria_labels", []):
                if any(kw in label.lower() for kw in ['gusta', 'encanta', 'comenta', 'compartid', 'visual', 'reacci', 'reaction', 'comment', 'share', 'view', 'persona']):
                    task_logger.info(f"  ARIA-LABEL: {label[:120]}")
            for text in js_data.get("engagement_texts", []):
                if any(kw in text.lower() for kw in ['comenta', 'compartid', 'visual', 'reaction', 'reacci', 'view', 'mil']):
                    task_logger.info(f"  ENGAGEMENT-TEXT: {text[:120]}")
            for text in js_data.get("button_texts", []):
                if any(kw in text.lower() for kw in ['comenta', 'compartid', 'visual', 'reacci', 'reaction', 'view', 'mil']):
                    task_logger.info(f"  BUTTON-TEXT: {text[:120]}")
            
            # Parse aria-labels for engagement data
            # Facebook ES format: "Me gusta: 263 personas", "Me encanta: 20 personas"
            reaction_types_total = 0
            for label in js_data.get("aria_labels", []):
                # Spanish reaction aria-labels: "Me gusta: X personas", "Me encanta: X personas", etc.
                reaction_match = re.search(r'(?:Me gusta|Me encanta|Me divierte|Me asombra|Me entristece|Me enoja|Like|Love|Haha|Wow|Sad|Angry):\s*([\d,.]+)\s*persona', label, re.IGNORECASE)
                if reaction_match:
                    count = int(reaction_match.group(1).replace(',', '').replace('.', ''))
                    reaction_types_total += count
                    
                # Comments from aria-label
                if not scraped_data.get("comments"):
                    m = re.search(r'([\d,.]+)\s*(?:comments?|comentarios)', label, re.IGNORECASE)
                    if m:
                        scraped_data["comments"] = m.group(1)
                
                # Views from aria-label
                if not scraped_data.get("views"):
                    m = re.search(r'([\d,.]+)\s*(?:mil\s+)?(?:views?|visualizaciones|reproducciones|plays?|vistas)', label, re.IGNORECASE)
                    if m:
                        scraped_data["views"] = m.group(0).strip()
            
            # If we summed individual reaction types, use that as total
            if reaction_types_total > 0 and not scraped_data.get("reactions"):
                scraped_data["reactions"] = str(reaction_types_total)
            
            # Parse engagement text from spans and buttons
            all_texts = js_data.get("engagement_texts", []) + js_data.get("button_texts", [])
            for text in all_texts:
                # Comments: "16 comentarios"
                if not scraped_data.get("comments"):
                    m = re.search(r'([\d,.]+)\s*(?:comments?|comentarios)', text, re.IGNORECASE)
                    if m:
                        scraped_data["comments"] = m.group(1)
                
                # Shares: "38 veces compartido" or "38 shares"
                if not scraped_data.get("shares"):
                    m = re.search(r'([\d,.]+)\s*(?:veces compartido|shares?|compartido)', text, re.IGNORECASE)
                    if m:
                        scraped_data["shares"] = m.group(1)
                
                # Views: "5,5 mil visualizaciones" or "5.5K views"
                if not scraped_data.get("views"):
                    m = re.search(r'([\d,.]+)\s*mil\s+(?:visualizaciones|reproducciones|vistas)', text, re.IGNORECASE)
                    if m:
                        scraped_data["views"] = m.group(0).strip()
                    else:
                        m = re.search(r'([\d,.]+[KMkm]?)\s*(?:views?|visualizaciones|reproducciones|vistas)', text, re.IGNORECASE)
                        if m:
                            scraped_data["views"] = m.group(0).strip()
                
                # Reactions total: "Todas las reacciones:\n291"
                if not scraped_data.get("reactions"):
                    if "reacciones" in text.lower() or "reactions" in text.lower():
                        m = re.search(r'([\d,.]+)', text)
                        if m:
                            scraped_data["reactions"] = m.group(1)
            
            # Video data from JS
            if js_data.get("video_src"):
                scraped_data["video_src"] = js_data["video_src"]
            if js_data.get("video_poster"):
                scraped_data["video_poster"] = js_data["video_poster"]
            if js_data.get("video_duration"):
                scraped_data["video_duration_seconds"] = js_data["video_duration"]
            
            # Post date
            if js_data.get("post_date"):
                scraped_data["post_date"] = js_data["post_date"]
                
        except Exception as e:
            task_logger.warning(f"JS extraction error: {e}")

        # --- LAYER 5: Page body text regex fallback ---
        try:
            page_text = await page.inner_text("body")
            
            if not scraped_data.get("comments"):
                m = re.search(r'([\d,.]+)\s*(?:comments?|comentarios)', page_text, re.IGNORECASE)
                if m:
                    scraped_data["comments"] = m.group(1)
            
            if not scraped_data.get("views"):
                # Match "5,5 mil visualizaciones" format
                m = re.search(r'([\d,.]+\s*mil)\s*(?:visualizaciones|reproducciones|vistas)', page_text, re.IGNORECASE)
                if m:
                    scraped_data["views"] = m.group(0).strip()
                else:
                    m = re.search(r'([\d,.]+[KMkm]?)\s*(?:views?|visualizaciones|reproducciones|plays?|vistas)', page_text, re.IGNORECASE)
                    if m:
                        scraped_data["views"] = m.group(0).strip()
                        
            if not scraped_data.get("reactions"):
                m = re.search(r'(?:Todas las reacciones:?\s*)([\d,.]+)', page_text, re.IGNORECASE)
                if m:
                    scraped_data["reactions"] = m.group(1)
                else:
                    m = re.search(r'([\d,.]+)\s*(?:reactions?|reacciones)', page_text, re.IGNORECASE)
                    if m:
                        scraped_data["reactions"] = m.group(1)
            
            if not scraped_data.get("shares"):
                m = re.search(r'([\d,.]+)\s*(?:veces compartido|shares?)', page_text, re.IGNORECASE)
                if m:
                    scraped_data["shares"] = m.group(1)
        except Exception as e:
            task_logger.warning(f"Page text extraction error: {e}")

        # --- LAYER 6: DOM element fallbacks ---
        # Caption from visible text (if OG description didn't capture it)
        if not scraped_data.get("og_description"):
            try:
                caption_selectors = [
                    "div[data-ad-preview='message']",
                    "div[data-ad-comet-preview='message']",
                    "div[dir='auto'][style*='text-align']",
                ]
                for sel in caption_selectors:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        text = await el.text_content()
                        if text and len(text.strip()) > 5:
                            scraped_data["caption"] = text.strip()
                            break
            except:
                pass

        # Username / Page Name
        if not scraped_data.get("author_from_title"):
            try:
                user_selectors = [
                    "h2 a[role='link']",
                    "h3 a[role='link']",
                    "strong a[role='link']",
                    "h2 a", "h3 a",
                    "a[aria-label][role='link'] strong",
                ]
                for sel in user_selectors:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        text = await el.text_content()
                        if text and len(text.strip()) > 1 and text.strip().lower() not in ["facebook", "log in", "sign up", "privacy", "iniciar sesión"]:
                            scraped_data["username"] = text.strip()
                            href = await el.get_attribute("href")
                            if href:
                                scraped_data["user_link"] = href
                            break
            except:
                pass

        # Video element
        try:
            video_el = page.locator("video").first
            if await video_el.count() > 0:
                src = await video_el.get_attribute("src")
                poster = await video_el.get_attribute("poster")
                if src and not scraped_data.get("video_src"):
                    scraped_data["video_src"] = src
                if poster and not scraped_data.get("video_poster"):
                    scraped_data["video_poster"] = poster
        except:
            pass

        # Build clean result
        # Use OG data as primary, fill gaps with DOM data
        author = scraped_data.get("author_from_title") or scraped_data.get("username")
        description = scraped_data.get("og_description") or scraped_data.get("meta_description") or scraped_data.get("caption")
        clean_caption = scraped_data.get("clean_caption") or description
        
        final_data = {
            "author": author,
            "caption": clean_caption,
            "description": description,
            "image": scraped_data.get("og_image"),
            "video_url": scraped_data.get("og_video_secure_url") or scraped_data.get("og_video_url") or scraped_data.get("og_video") or scraped_data.get("video_src"),
            "video_type": scraped_data.get("og_video_type"),
            "video_duration_seconds": scraped_data.get("video_duration_seconds"),
            "video_thumbnail": scraped_data.get("og_image") or scraped_data.get("video_poster") or scraped_data.get("thumbnail"),
            "reactions": scraped_data.get("reactions"),
            "shares": scraped_data.get("shares"),
            "comments": scraped_data.get("comments"),
            "views": scraped_data.get("views"),
            "post_date": scraped_data.get("post_date"),
            "user_link": scraped_data.get("user_link"),
            "canonical_url": scraped_data.get("og_url"),
            "content_type": scraped_data.get("og_type"),
            "raw_og_data": {k: v for k, v in scraped_data.items() if k.startswith("og_") or k in ["meta_description", "page_title"]},
        }
        # Remove None values for cleaner output
        final_data = {k: v for k, v in final_data.items() if v is not None}
        
        # Log all scraped data for debugging
        task_logger.info(f"Final scraped data keys: {list(scraped_data.keys())}")
        task_logger.info(f"Final output data keys: {list(final_data.keys())}")
        if final_data.get("raw_og_data"):
            task_logger.info(f"Raw OG data: {final_data['raw_og_data']}")
        else:
            task_logger.warning("No raw_og_data found - this indicates no OG tags were extracted")

        result["data"] = final_data
        result["status"] = "success"
        
        task_logger.info("Scraping completed successfully.")

    except Exception as e:
        task_logger.error(f"Fatal scraping error: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
    finally:
        # Cleanup
        if context:
            await context.close()
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()
        
        # Send Webhook
        await send_webhook(result, task_logger)

# --- FastAPI App ---
app = FastAPI(title="Minimal FB Scraper")

@app.post("/scrape", status_code=202, response_model=ScrapeTaskResponse)
async def scrape_endpoint(request: ScrapeRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    
    # Add background task
    background_tasks.add_task(run_scraper, task_id, str(request.url))
    
    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "Scraping started in background"
    }

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80)
