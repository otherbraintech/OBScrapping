import os
import asyncio
from typing import Dict, Any, Optional
from ..base import BaseScraper
from .utils import _normalize_count

class FacebookBaseScraper(BaseScraper):
    def __init__(self, task_id: str, logger):
        super().__init__(task_id, logger)
        self.cookies = self._load_cookies()

    def _load_cookies(self) -> Dict[str, str]:
        raw = os.getenv("FACEBOOK_COOKIES", "")
        if not raw:
            return {}
        try:
            return dict(item.split("=", 1) for item in raw.split("; "))
        except:
            self.logger.warning("Invalid FACEBOOK_COOKIES format.")
            return {}

    async def dismiss_login_banner(self):
        """Attempt to close a login popup/banner without blocking navigation."""
        if not self.page:
            return
        # Common close/dismiss selectors for the login overlay
        close_selectors = [
            "div[aria-label='Close']",
            "div[aria-label='Cerrar']",
            "[data-testid='login_wall_dismiss']",
            "div[role='dialog'] div[aria-label='Close']",
        ]
        for sel in close_selectors:
            try:
                btn = self.page.locator(sel)
                if await btn.count() > 0:
                    self.logger.info(f"Dismissing login banner ({sel})...")
                    await btn.first.click()
                    await asyncio.sleep(1.5)
                    return  # successfully dismissed
            except:
                pass

    async def check_restricted(self) -> Optional[str]:
        """
        Detects if content is truly blocked (not just showing a dismissible banner).
        Strategy:
         1. Hard block: URL redirected to /login or /checkpoint
         2. Try to dismiss any login popup banner
         3. Soft check: only flag as restricted if the page has NO useful content at all
        """
        if not self.page:
            return None

        # Step 1: Hard URL-based block
        current_url = self.page.url or ""
        if "login.php" in current_url or "checkpoint" in current_url:
            self.logger.error(f"Hard block detected - URL redirected to: {current_url}")
            return "Blocked: redirected to login/checkpoint page"

        # Step 2: Try to dismiss any overlay/banner
        await self.dismiss_login_banner()

        # Step 3: Re-check the page content AFTER attempting to dismiss
        content = await self.page.content()
        low_content = content.lower()

        # These are real hard blocks (no content is accessible)
        if "este contenido no está disponible" in low_content or "this content isn't available" in low_content:
            return "Content not available (possibly deleted or private)"

        # Only flag as login wall if page is extremely short (pure login redirect)
        # A banner on a real post still shows the full page HTML (~50KB+)
        if len(content) < 3000 and any(kw in low_content for kw in ["inicia sesión", "log in", "sign in"]):
            return "Restricted content (requires login or valid cookies)"

        # Otherwise, assume the content is visible (banner is dismissible)
        return None

    async def is_logged_in(self) -> bool:
        if not self.page:
            return False
        content = await self.page.content()
        return not any(kw in content.lower() for kw in ["log in", "iniciar sesión", "registrarse", "login"])
