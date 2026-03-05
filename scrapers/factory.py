import re
from typing import Type
from .base import BaseScraper
from .facebook.reel import FacebookReelScraper
from .facebook.post import FacebookPostScraper
from .facebook.page import FacebookPageScraper

class ScraperFactory:
    @staticmethod
    def get_scraper_class(url: str, scrape_type: str = None) -> Type[BaseScraper]:
        url_low = url.lower()
        
        # Manual override by type
        if scrape_type == "page_feed" or scrape_type == "public_profile":
            return FacebookPageScraper
        if scrape_type == "reel":
            return FacebookReelScraper
        if scrape_type == "post":
            return FacebookPostScraper

        if "facebook.com" in url_low or "fb.watch" in url_low:
            # Handle profile/page/feed URLs
            # URLs like /PAGENAME/, /PAGENAME/reels, /PAGENAME/videos, /profile.php?id=...
            # but NOT /reel/ID or /posts/ID
            is_individual = (
                "/reel/" in url_low or 
                "/share/r/" in url_low or
                "/share/v/" in url_low or
                "/share/p/" in url_low or
                "/videos/" in url_low or 
                "/posts/" in url_low or 
                "/permalink/" in url_low or
                "fb.watch/" in url_low or
                "story.php" in url_low
            )
            
            if not is_individual:
                # Likely a page or profile
                return FacebookPageScraper
            
            # Individual items
            if "/share/v/" in url_low or "/share/r/" in url_low:
                return FacebookReelScraper
            
            if "/reel/" in url_low:
                return FacebookReelScraper
            
            # Default to post for other individual links
            return FacebookPostScraper
            
        # Placeholders for future platforms
        if "instagram.com" in url_low:
            raise NotImplementedError("Instagram scraper not yet modularized")
        if "tiktok.com" in url_low:
            raise NotImplementedError("TikTok scraper not yet modularized")
            
        raise ValueError(f"No scraper found for URL: {url}")
