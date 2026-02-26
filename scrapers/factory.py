import re
from typing import Type
from .base import BaseScraper
from .facebook.reel import FacebookReelScraper
from .facebook.post import FacebookPostScraper

class ScraperFactory:
    @staticmethod
    def get_scraper_class(url: str) -> Type[BaseScraper]:
        url_low = url.lower()
        
        if "facebook.com" in url_low or "fb.watch" in url_low:
            # Handle share URLs like https://www.facebook.com/share/v/14VSX1MV1WL/
            # For now, all share URLs are treated as reels. If a distinction is needed
            # between shared posts and shared reels, more sophisticated parsing would be required.
            if "/share/v/" in url_low or "/share/r/" in url_low or "/share/p/" in url_low:
                # Assuming shared videos/reels are the primary use case for these share links.
                # If a shared post needs to be handled differently, this logic would need refinement.
                return FacebookReelScraper
            
            if "/reel/" in url_low or "/reels/" in url_low:
                return FacebookReelScraper
            return FacebookPostScraper
            
        # Placeholders for future platforms
        if "instagram.com" in url_low:
            raise NotImplementedError("Instagram scraper not yet modularized")
        if "tiktok.com" in url_low:
            raise NotImplementedError("TikTok scraper not yet modularized")
            
        raise ValueError(f"No scraper found for URL: {url}")
