import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from playwright.async_api import BrowserContext, Page, async_playwright
from playwright_stealth import stealth_async

class BaseScraper(ABC):
    def __init__(self, task_id: str, logger: logging.Logger):
        self.task_id = task_id
        self.logger = logger
        self.playwright: Any = None
        self.browser: Any = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    @abstractmethod
    async def run(self, url: str, **kwargs) -> Dict[str, Any]:
        """Core execution logic for the scraper."""
        pass

    async def setup_browser(self, proxy_server: Optional[str] = None, user_agent: Optional[str] = None):
        """Standard browser setup with stealth and optional proxy."""
        self.logger.info("Setting up browser...")
        
        self.playwright = await async_playwright().start()
        
        browser_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--disable-gpu"
        ]
        
        launch_kwargs = {
            "headless": True,
            "args": browser_args
        }
        if proxy_server:
            launch_kwargs["proxy"] = {"server": proxy_server}
            
        self.browser = await self.playwright.chromium.launch(**launch_kwargs)
        
        context_kwargs = {}
        if user_agent:
            context_kwargs["user_agent"] = user_agent
        else:
            # Default UA
            context_kwargs["user_agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
        self.context = await self.browser.new_context(**context_kwargs)
        self.page = await self.context.new_page()
        # Apply stealth
        await stealth_async(self.page)
        self.logger.info("Browser and page ready with stealth.")

    async def close(self):
        """Cleanup browser resources."""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
        self.logger.info("Browser closed.")

    def format_error(self, message: str) -> Dict[str, Any]:
        return {
            "status": "error",
            "task_id": self.task_id,
            "message": message
        }
