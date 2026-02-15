import asyncio
import random
import json
import logging
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# Setup basic logging to console
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("test")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

async def simulate_human_behavior(page):
    logger.info("Simulating human behavior (scrolling)...")
    try:
        await page.mouse.move(random.randint(100, 500), random.randint(100, 500))
        await asyncio.sleep(2)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(3)
        await page.evaluate("window.scrollTo(0, 0)") # Scroll back up slightly
    except Exception as e:
        logger.warning(f" behavior simulation issue: {e}")

async def scrape_url(url: str):
    logger.info(f"Starting local test for: {url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent=USER_AGENTS[0],
            viewport={"width": 1280, "height": 720},
            locale="en-US"
        )
        page = await context.new_page()
        await stealth_async(page)
        
        logger.info("Navigating...")
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            logger.error(f"Navigation error: {e}")
            return

        await asyncio.sleep(5) # Wait for render
        
        # Check title
        title = await page.title()
        logger.info(f"Page Title: {title}")
        
        await simulate_human_behavior(page)
        
        data = {}
        
        # 1. Caption
        try:
            caption_el = page.locator("div[data-ad-preview='message']").first
            if await caption_el.count() == 0:
                 caption_el = page.locator("span[dir='auto']").first 
            if await caption_el.count() > 0:
                data["caption"] = await caption_el.text_content()
        except: pass

        # 2. Reactions
        try:
            reactions_el = page.locator("div[aria-label*='reaction']").first
            if await reactions_el.count() > 0:
                 data["reactions"] = await reactions_el.text_content()
        except: pass
        
        # 3. Username
        try:
            user_el = page.locator("h3 a, h2 a, span > a[role='link']").first
            if await user_el.count() > 0:
                data["username"] = await user_el.text_content()
        except: pass

        logger.info("-" * 30)
        logger.info("SCRAPED DATA RESULT:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info("-" * 30)

        await browser.close()

if __name__ == "__main__":
    url = "https://www.facebook.com/share/r/1agjhqdRwv/"
    asyncio.run(scrape_url(url))
