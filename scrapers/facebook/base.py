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

    async def is_logged_in(self) -> bool:
        # Check for login markers or redirect to login
        if not self.page:
            return False
        content = await self.page.content()
        return not any(kw in content.lower() for kw in ["log in", "iniciar sesión", "registrarse", "login"])

    async def check_restricted(self) -> Optional[str]:
        """Detects if content is private, restricted, or requires login."""
        if not self.page:
            return None
        content = await self.page.content()
        low_content = content.lower()
        if "este contenido no está disponible" in low_content or "this content isn't available" in low_content:
            return "Content not available (possibly deleted or private)"
        if any(kw in low_content for kw in ["inicia sesión", "log in to see this", "checkpoint"]):
            return "Restricted content (requires login or valid cookies)"
        return None
