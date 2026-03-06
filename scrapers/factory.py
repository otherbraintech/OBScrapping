import re
from typing import Type, Optional
from .base import BaseScraper
from .facebook.reel import FacebookReelScraper
from .facebook.post import FacebookPostScraper
from .facebook.page import FacebookPageScraper

class ScraperFactory:
    @staticmethod
    def get_scraper_class(url: str, scrape_type: Optional[str] = None) -> Type[BaseScraper]:
        url_low = url.lower()
        
        # 1. URL Pattern Detection (Highest Priority for Reels/Posts)
        # Reel URLs
        is_reel = (
            "/reel/" in url_low or 
            "/share/r/" in url_low or
            "fb.watch/" in url_low
        )
        
        # Post URLs
        is_post = (
            "/posts/" in url_low or 
            "/permalink/" in url_low or
            "story.php" in url_low or
            "/share/p/" in url_low or
            "/photo" in url_low
        )

        # Video/Reel overlap
        is_video = (
            "/videos/" in url_low or
            "/share/v/" in url_low
        )

        # 2. Page Feed Detection
        # If it doesn't look like an individual item, it's likely a page
        is_individual = is_reel or is_post or is_video
        
        # 3. Decision Logic
        # Explicit type overrides (if they make sense for the URL)
        if scrape_type == "page_feed" or scrape_type == "public_profile":
            return FacebookPageScraper
            
        if scrape_type == "reel" and is_reel:
            return FacebookReelScraper
            
        if scrape_type == "post" and is_post:
            return FacebookPostScraper

        # If URL structure strongly suggests an individual item
        if is_reel:
            return FacebookReelScraper
        if is_post:
            return FacebookPostScraper
        if is_video:
            # For /videos/, we check if it's a specific video or the video tab
            # e.g. /page/videos/ vs /videos/123/
            if re.search(r'/videos/\d+/', url_low) or re.search(r'v=\d+', url_low):
                return FacebookPostScraper # or ReelsScraper if it's vertical
            
        # Default for Page URLs (e.g. facebook.com/pagename)
        if "facebook.com" in url_low:
            if not is_individual:
                return FacebookPageScraper
            # If it IS individual but we didn't catch type, try to guess
            if "/reel/" in url_low: return FacebookReelScraper
            return FacebookPostScraper 

            
        # Placeholders for future platforms
        if "instagram.com" in url_low:
            raise NotImplementedError("Instagram scraper not yet modularized")
        if "tiktok.com" in url_low:
            raise NotImplementedError("TikTok scraper not yet modularized")
            
        raise ValueError(f"No scraper found for URL: {url}")
