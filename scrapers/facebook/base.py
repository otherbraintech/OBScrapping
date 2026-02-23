import os
import asyncio
from typing import Dict, Any, List, Optional
from ..base import BaseScraper
from .utils import _normalize_count

class FacebookBaseScraper(BaseScraper):
    def __init__(self, task_id: str, logger):
        super().__init__(task_id, logger)

    def _build_cookies(self) -> List[Dict[str, Any]]:
        """Reads Facebook session cookies from environment variables."""
        cookies = []
        cookie_defs = [
            ("c_user", "FB_COOKIE_C_USER", False, True),
            ("xs",     "FB_COOKIE_XS",     True,  True),
            ("datr",   "FB_COOKIE_DATR",   True,  True),
            ("fr",     "FB_COOKIE_FR",     True,  True),
            ("sb",     "FB_COOKIE_SB",     True,  True),
        ]
        for name, env_var, http_only, secure in cookie_defs:
            value = os.getenv(env_var, "")
            if value:
                cookies.append({
                    "name": name,
                    "value": value,
                    "domain": ".facebook.com",
                    "path": "/",
                    "httpOnly": http_only,
                    "secure": secure,
                    "sameSite": "None",
                })
        return cookies

    async def inject_cookies(self):
        """Injects Facebook session cookies into the browser context before navigation."""
        if not self.context:
            self.logger.warning("No browser context available to inject cookies.")
            return

        cookies = self._build_cookies()
        if cookies:
            await self.context.add_cookies(cookies)
            self.logger.info(f"Injected {len(cookies)} Facebook session cookies.")
        else:
            self.logger.warning(
                "No Facebook cookies configured (FB_COOKIE_C_USER / FB_COOKIE_XS not set). "
                "Scraping as anonymous user — engagement data may be limited."
            )

    async def dismiss_login_banner(self):
        """Attempt to close a login popup/banner without blocking navigation."""
        if not self.page:
            return
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
                    return
            except Exception:
                pass

    async def check_restricted(self) -> Optional[str]:
        """
        Detects if content is truly blocked.
        Only blocks on hard URL redirects or genuinely empty pages.
        """
        if not self.page:
            return None

        # Hard URL-based block (real redirect)
        current_url = self.page.url or ""
        if "login.php" in current_url or "checkpoint" in current_url:
            self.logger.error(f"Hard block detected — redirected to: {current_url}")
            return "Blocked: redirected to login/checkpoint page"

        # Try to dismiss any banner first
        await self.dismiss_login_banner()

        # Re-check content AFTER dismissal
        content = await self.page.content()
        low_content = content.lower()

        if "este contenido no está disponible" in low_content or "this content isn't available" in low_content:
            return "Content not available (possibly deleted or private)"

        # Only hard-fail if page is very short AND has login prompt (pure redirect)
        if len(content) < 3000 and any(kw in low_content for kw in ["inicia sesión", "log in", "sign in"]):
            return "Restricted content (requires login or valid cookies)"

        return None

    async def is_logged_in(self) -> bool:
        if not self.page:
            return False
        content = await self.page.content()
        return not any(kw in content.lower() for kw in ["log in", "iniciar sesión", "registrarse", "login"])
