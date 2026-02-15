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
    """Simulates scrolling and mouse movements."""
    task_logger.info("Simulating human behavior (scrolling)...")

    # Mouse movement
    try:
        await page.mouse.move(random.randint(100, 500), random.randint(100, 500))
        await asyncio.sleep(random.uniform(1.0, 3.0))
    except Exception as e:
        task_logger.warning(f"Mouse move failed: {e}")

    # Scroll logic
    try:
        for _ in range(random.randint(2, 4)):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(2.0, 5.0))
            # Scroll up a bit sometimes
            if random.random() > 0.7:
                 await page.evaluate("window.scrollBy(0, -300)")
                 await asyncio.sleep(random.uniform(1.0, 3.0))
    except Exception as e:
        task_logger.warning(f"Scroll failed: {e}")

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

        context = await browser.new_context(
            user_agent=user_agent,
            viewport=viewport,
            locale="en-US",
            timezone_id="America/New_York",
            device_scale_factor=random.choice([1, 1.5, 2]),
            has_touch=random.choice([True, False]),
            is_mobile=False # Desktop simulation usually better for stealth than mobile
        )

        page = await context.new_page()

        # Apply stealth
        await stealth_async(page)
        
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
        for tag in og_tags:
            try:
                el = page.locator(f'meta[property="{tag}"]')
                if await el.count() > 0:
                    value = await el.first.get_attribute("content")
                    key = tag.replace(":", "_").replace(".", "_")
                    scraped_data[key] = value
            except Exception as e:
                task_logger.warning(f"Error reading {tag}: {e}")

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

        # --- LAYER 3: Dynamic content from page text ---
        page_text = await page.inner_text("body")

        # Extract engagement numbers using regex patterns
        # Reactions/Likes
        try:
            patterns_reactions = [
                r'([\d,.]+[KMkm]?)\s*(?:reactions?|reacciones)',
                r'([\d,.]+[KMkm]?)\s*(?:likes?|me gusta)',
                r'([\d,.]+[KMkm]?)\s*(?:people reacted|personas reaccionaron)',
            ]
            for pattern in patterns_reactions:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    scraped_data["reactions"] = match.group(1)
                    break
        except:
            pass

        # Shares
        try:
            patterns_shares = [
                r'([\d,.]+[KMkm]?)\s*(?:shares?|compartido|veces compartido)',
                r'([\d,.]+[KMkm]?)\s*(?:times shared)',
            ]
            for pattern in patterns_shares:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    scraped_data["shares"] = match.group(1)
                    break
        except:
            pass

        # Comments
        try:
            patterns_comments = [
                r'([\d,.]+[KMkm]?)\s*(?:comments?|comentarios)',
            ]
            for pattern in patterns_comments:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    scraped_data["comments"] = match.group(1)
                    break
        except:
            pass

        # Views
        try:
            patterns_views = [
                r'([\d,.]+[KMkm]?)\s*(?:views?|visualizaciones|reproducciones)',
                r'([\d,.]+[KMkm]?)\s*(?:plays?)',
            ]
            for pattern in patterns_views:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    scraped_data["views"] = match.group(1)
                    break
        except:
            pass

        # --- LAYER 4: DOM element fallbacks ---
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
                    if text and len(text.strip()) > 1 and text.strip().lower() not in ["facebook", "log in", "sign up", "privacy"]:
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
                if src:
                    scraped_data["video_src"] = src
                if poster:
                    scraped_data["thumbnail"] = poster
        except:
            pass

        # Build clean result
        # Use OG data as primary, fill gaps with DOM data
        final_data = {
            "title": scraped_data.get("og_title") or scraped_data.get("page_title"),
            "description": scraped_data.get("og_description") or scraped_data.get("meta_description") or scraped_data.get("caption"),
            "image": scraped_data.get("og_image"),
            "video_url": scraped_data.get("og_video_secure_url") or scraped_data.get("og_video_url") or scraped_data.get("og_video") or scraped_data.get("video_src"),
            "video_type": scraped_data.get("og_video_type"),
            "username": scraped_data.get("username"),
            "user_link": scraped_data.get("user_link"),
            "reactions": scraped_data.get("reactions"),
            "shares": scraped_data.get("shares"),
            "comments": scraped_data.get("comments"),
            "views": scraped_data.get("views"),
            "thumbnail": scraped_data.get("og_image") or scraped_data.get("thumbnail"),
            "canonical_url": scraped_data.get("og_url"),
            "content_type": scraped_data.get("og_type"),
            "raw_og_data": {k: v for k, v in scraped_data.items() if k.startswith("og_")},
        }
        # Remove None values for cleaner output
        final_data = {k: v for k, v in final_data.items() if v is not None}

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
