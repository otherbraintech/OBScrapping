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
            if "/reel/" in url_low or "/share/v/" in url_low:
                return FacebookReelScraper
            return FacebookPostScraper
            
        # Placeholders for future platforms
        if "instagram.com" in url_low:
            raise NotImplementedError("Instagram scraper not yet modularized")
        if "tiktok.com" in url_low:
            raise NotImplementedError("TikTok scraper not yet modularized")
            
        raise ValueError(f"No scraper found for URL: {url}")
