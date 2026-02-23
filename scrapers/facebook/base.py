import os
import json
import asyncio
from typing import Dict, Any, List, Optional
from ..base import BaseScraper
from .utils import _normalize_count

class FacebookBaseScraper(BaseScraper):
    def __init__(self, task_id: str, logger):
        super().__init__(task_id, logger)

    def _build_cookies(self) -> List[Dict[str, Any]]:
        """
        Reads Facebook session cookies from environment variables.

        Supports two formats:
        1. Individual vars: FB_COOKIE_C_USER, FB_COOKIE_XS, FB_COOKIE_DATR, FB_COOKIE_FR, FB_COOKIE_SB
        2. Legacy JSON array string: FACEBOOK_COOKIES='[{"name": "c_user", "value": "...", ...}]'
        3. Legacy key=value string: FACEBOOK_COOKIES='c_user=123; xs=abc; ...'
        """
        cookies: List[Dict[str, Any]] = []

        # --- Format 1: Individual env vars (preferred) ---
        individual_defs = [
            ("c_user", "FB_COOKIE_C_USER", False, True),
            ("xs",     "FB_COOKIE_XS",     True,  True),
            ("datr",   "FB_COOKIE_DATR",   True,  True),
            ("fr",     "FB_COOKIE_FR",     True,  True),
            ("sb",     "FB_COOKIE_SB",     True,  True),
        ]
        found_individual = False
        for name, env_var, http_only, secure in individual_defs:
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
                found_individual = True

        if found_individual:
            return cookies

        # --- Format 2 & 3: Legacy FACEBOOK_COOKIES env var ---
        raw = os.getenv("FACEBOOK_COOKIES", "").strip()
        if not raw:
            return []

        # Try JSON array
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    # Add domain/path defaults if missing
                    result = []
                    for c in parsed:
                        if isinstance(c, dict) and "name" in c and "value" in c:
                            c.setdefault("domain", ".facebook.com")
                            c.setdefault("path", "/")
                            result.append(c)
                    self.logger.info(f"Loaded {len(result)} cookies from FACEBOOK_COOKIES (JSON format).")
                    return result
            except json.JSONDecodeError:
                pass

        # Try key=value string: "c_user=123; xs=abc; ..."
        try:
            kv_map = {
                "c_user": (False, True),
                "xs": (True, True),
                "datr": (True, True),
                "fr": (True, True),
                "sb": (True, True),
            }
            result = []
            for part in raw.split(";"):
                part = part.strip()
                if "=" in part:
                    name, _, value = part.partition("=")
                    name = name.strip()
                    value = value.strip()
                    if name and value:
                        http_only, secure = kv_map.get(name, (False, True))
                        result.append({
                            "name": name,
                            "value": value,
                            "domain": ".facebook.com",
                            "path": "/",
                            "httpOnly": http_only,
                            "secure": secure,
                            "sameSite": "None",
                        })
            if result:
                self.logger.info(f"Loaded {len(result)} cookies from FACEBOOK_COOKIES (key=value format).")
                return result
        except Exception:
            pass

        return []

    async def inject_cookies(self):
        """Injects Facebook session cookies into the browser context before navigation."""
        if not self.context:
            self.logger.warning("No browser context to inject cookies into.")
            return

        cookies = self._build_cookies()
        if cookies:
            await self.context.add_cookies(cookies)
            names = [c["name"] for c in cookies]
            self.logger.info(f"Injected {len(cookies)} Facebook cookies: {names}")
        else:
            self.logger.warning(
                "No Facebook cookies found. Set FB_COOKIE_C_USER + FB_COOKIE_XS env vars "
                "or FACEBOOK_COOKIES env var. Scraping as anonymous — engagement data may be missing."
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
                    self.logger.info(f"Dismissing login banner: {sel}")
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

        current_url = self.page.url or ""
        if "login.php" in current_url or "checkpoint" in current_url:
            self.logger.error(f"Hard block detected — redirected to: {current_url}")
            return "Blocked: redirected to login/checkpoint page"

        await self.dismiss_login_banner()

        content = await self.page.content()
        low_content = content.lower()

        if "este contenido no está disponible" in low_content or "this content isn't available" in low_content:
            return "Content not available (possibly deleted or private)"

        # Only hard-fail if page is very short AND has a login-only prompt
        if len(content) < 3000 and any(kw in low_content for kw in ["inicia sesión", "log in", "sign in"]):
            return "Restricted content (requires login or valid cookies)"

        return None

    async def is_logged_in(self) -> bool:
        if not self.page:
            return False
        content = await self.page.content()
        return not any(kw in content.lower() for kw in ["log in", "iniciar sesión", "registrarse", "login"])
