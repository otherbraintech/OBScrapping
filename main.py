import asyncio
import json
import logging
import os
import uuid
import httpx
import random
from datetime import datetime
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl

# Load environment variables
load_dotenv()

# --- Modular Scrapers ---
from scrapers.factory import ScraperFactory

# --- Configuration ---
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
FACEBOOK_COOKIES = os.getenv("FACEBOOK_COOKIES", "")

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("fb_scraper")
logger.setLevel(logging.INFO)

# --- Models ---
class ScrapeRequest(BaseModel):
    url: HttpUrl
    network: Optional[str] = "facebook"
    type: Optional[str] = "reel"
    debug_raw: Optional[bool] = False
    raw_snippet_len: Optional[int] = 5000
    extra_wait_seconds: Optional[float] = 0.0
    dump_all: Optional[bool] = False

class ScrapeTaskResponse(BaseModel):
    status: str
    task_id: str
    message: str

# --- Helper Functions ---
class TaskLogger(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[{self.extra.get('task_id', 'unknown')}] {msg}", kwargs

async def send_webhook(data: Dict[str, Any], task_logger):
    """Sends the result to the configured webhook."""
    if not WEBHOOK_URL:
        task_logger.warning("WEBHOOK_URL not configured, skipping webhook.")
        return
    
    task_logger.info(f"Sending webhook to {WEBHOOK_URL}...")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(WEBHOOK_URL, json=data)
            response.raise_for_status()
            task_logger.info(f"Webhook sent successfully: {response.status_code}")
        except httpx.HTTPError as e:
            task_logger.error(f"Webhook failed: {e}")

# --- Orchestrator ---
async def run_scraper(
    task_id: str,
    url: str,
    debug_raw: bool = False,
    raw_snippet_len: int = 5000,
    extra_wait_seconds: float = 0.0,
    dump_all: bool = False,
):
    task_logger = TaskLogger(logger, {"task_id": task_id})
    task_logger.info(f"Starting modular scraper run for {url}")
    
    result = {
        "task_id": task_id,
        "url": url,
        "status": "pending",
        "scraped_at": datetime.utcnow().isoformat(),
        "data": {},
        "error": None
    }

    scraper = None
    try:
        # Get appropriate scraper class from factory
        scraper_cls = ScraperFactory.get_scraper_class(url)
        scraper = scraper_cls(task_id, logger)
        
        # Setup and Run
        # Note: You can pass generic proxy/UA settings from main config here
        await scraper.setup_browser()
        
        # Execute the scraping logic
        data = await scraper.run(
            url, 
            extra_wait_seconds=extra_wait_seconds, 
            debug_raw=debug_raw
        )
        
        if data.get("status") == "error":
            result["status"] = "error"
            result["error"] = data.get("message")
            result["data"] = data.get("data", {}) # Include any diagnostic data even on error
        else:
            result["status"] = "success"
            result["data"] = data.get("data", {})
            
    except Exception as e:
        task_logger.error(f"Fatal error in orchestrator: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
    finally:
        if scraper:
            await scraper.close()
            
        # Send the final result via webhook
        await send_webhook(result, task_logger)

# --- FastAPI App ---
app = FastAPI(title="Modular Social Scraper API")

@app.post("/scrape", response_model=ScrapeTaskResponse)
async def scrape_endpoint(request: ScrapeRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())

    # Add background task
    background_tasks.add_task(
        run_scraper,
        task_id,
        str(request.url),
        request.debug_raw or False,
        request.raw_snippet_len or 5000,
        request.extra_wait_seconds or 0.0,
        request.dump_all or False,
    )

    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "Scraping task accepted and running in background"
    }

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

if __name__ == "__main__":
    import uvicorn
    # In production, this is usually run via: uvicorn main:app --host 0.0.0.0 --port 80
    uvicorn.run(app, host="0.0.0.0", port=80)
