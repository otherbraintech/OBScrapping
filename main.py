import asyncio
import logging
import random
import uuid
import os
from datetime import datetime
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

import httpx
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_async

# --- Configuration ---
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL environment variable is not set")
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
    format="%(asctime)s [%(levelname)s] [%(task_id)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scraper.log", mode='a', encoding='utf-8')
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
        return f"{msg}", {**kwargs, "extra": {**self.extra}}

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

        # Parsing Logic
        task_logger.info("Parsing page content...")
        scraped_data = {}

        # 1. Caption / Text
        # Often in div[dir="auto"] inside the post container
        try:
            # Try specific selectors first
            caption_el = page.locator("div[data-ad-preview='message']").first
            if await caption_el.count() == 0:
                 caption_el = page.locator("span[dir='auto']").first # Fallback
            
            if await caption_el.count() > 0:
                scraped_data["caption"] = await caption_el.text_content()
            else:
                 # Last resort regex or broad search
                scraped_data["caption"] = None
        except Exception as e:
            task_logger.warning(f"Error extracting caption: {e}")

        # 2. Reactions / Likes
        # Try finding aria-label with "reactions" or "likes"
        try:
            # Look for common reaction 
            reactions_el = page.locator("span[role='toolbar']").first
            if await reactions_el.count() == 0:
                 # Check for the reaction summary line like "John Doe and 1.2K others"
                reactions_el = page.locator("div[aria-label*='reaction']").first

            # If that fails, try looking for the number
            if await reactions_el.count() > 0:
                scraped_data["reactions_raw"] = await reactions_el.text_content()
            else: 
                # Sometimes just a plain number next to an emoji
                pass 
                
            # Try to get numeric count specifically if possible (very hard on dynamic FB)
        except Exception as e:
            task_logger.warning(f"Error extracting reactions: {e}")

        # 3. Shares
        try:
             # Iterate through spans/divs that might contain 'shares'
            shares_el = page.get_by_text("shares", exact=False).first
            if await shares_el.count() > 0:
                scraped_data["shares_raw"] = await shares_el.text_content()
        except:
            pass

        # 4. Comments Count
        try:
            comments_el = page.get_by_text("comments", exact=False).first
            if await comments_el.count() > 0:
                scraped_data["comments_count_raw"] = await comments_el.text_content()
        except:
            pass

        # 5. Username / Page Name
        try:
            # Usually h2 or h3 or strong tag
            # Or inside an anchor tag that looks like a profile link
            # For Reels specifically, it might be different
            
            # Common pattern: h3 > span > a
            user_el = page.locator("h3 a, h2 a, span > a[role='link']").first
            # Filter out generic links like "Privacy"
            if await user_el.count() > 0:
                scraped_data["username"] = await user_el.text_content()
                scraped_data["user_link"] = await user_el.get_attribute("href")
        except Exception as e:
            task_logger.warning(f"Error extracting username: {e}")

        # 6. Date
        try:
            # Often an anchor with an aria-label containing the time or role="link" with hovercard
            # Or simplified: look for 'abbr' or 'time' tags, though FB uses complex layouts
            # Best bet: look for the timestamp link (often just below username)
            # It usually has the permalink as href
            
            # Locate all links and filter for ones that look like timestamps (short text, relative time)
            # This is hard to pinpoint, so we might skip or grab first potential match
            pass
        except:
             pass

        # 7. Video Source (if Reel)
        try:
            video_el = page.locator("video").first
            if await video_el.count() > 0:
                scraped_data["video_src"] = await video_el.get_attribute("src")
                scraped_data["thumbnail"] = await video_el.get_attribute("poster")
        except:
            pass
            
        # 8. Views
        try:
             views_el = page.get_by_text("views", exact=False).first
             if await views_el.count() > 0:
                 scraped_data["views_raw"] = await views_el.text_content()
        except:
            pass

        result["data"] = scraped_data
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
