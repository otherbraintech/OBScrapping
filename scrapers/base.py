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

    async def setup_browser(self, proxy_config: Optional[Dict[str, str]] = None, user_agent: Optional[str] = None):
        """Standard browser setup with stealth and optional proxy."""
        self.logger.info(f"Setting up browser (Proxy: {'Yes' if proxy_config else 'No'})...")
        
        try:
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
            if proxy_config:
                launch_kwargs["proxy"] = proxy_config
                self.logger.info(f"Proxy configured: server={proxy_config.get('server')}, username={proxy_config.get('username', 'N/A')}")
                
            self.browser = await self.playwright.chromium.launch(**launch_kwargs)
            
            context_kwargs = {}
            if user_agent:
                context_kwargs["user_agent"] = user_agent
            else:
                context_kwargs["user_agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                
            self.context = await self.browser.new_context(**context_kwargs)
            self.page = await self.context.new_page()
            # Apply stealth
            await stealth_async(self.page)

            # --- DIAGNOSTIC RESPONSES ---
            async def handle_response(response):
                try:
                    # Log status for the main page navigation
                    if response.request.resource_type == "document" and response.status >= 300:
                        self.logger.warning(f"[NET] Non-200 response: {response.status} {response.status_text} for {response.url}")
                    elif response.url == self.page.url:
                        self.logger.info(f"[NET] Main response status: {response.status} for {response.url}")
                except Exception:
                    pass
            
            self.page.on("response", lambda r: asyncio.create_task(handle_response(r)))

            self.logger.info("Browser and page ready with stealth and network logging.")
        except Exception as e:
            self.logger.error(f"Browser setup failed: {e}")
            await self.close()
            raise e

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

    def format_error(self, message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "status": "error",
            "task_id": self.task_id,
            "message": message,
            "data": data or {}
        }
