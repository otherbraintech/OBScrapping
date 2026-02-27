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
from database import SessionLocal, ScrapeRequest as DBScrapeRequest, ScrapeResult as DBScrapeResult, get_db
from sqlalchemy.orm import Session

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
            
        # DIAGNOSTIC: Log data received from scraper
        scraped_data = result.get("data", {})
        task_logger.info(f"DEBUG - SCRAPER DATA KEYS: {list(scraped_data.keys())}")

        clean_result = {
            "task_id": result.get("task_id"),
            "url": scraped_data.get("requested_url") or result.get("url"),
            "scraped_at": result.get("scraped_at"),
            "status": result.get("status"),
            "error": result.get("error"),
            "content_type": scraped_data.get("content_type", "unknown"),
            "metrics": {
                "reactions": scraped_data.get("reactions_count", 0),
                "comments": scraped_data.get("comments_count", 0),
                "shares": scraped_data.get("shares_count", 0),
                "views": scraped_data.get("views_count", 0),
            },
            "version": "1.0.9-fixed",
            "_debug": scraped_data.get("_debug", {})
        }

        # Ensure rawData for DB contains EVERYTHING including _debug
        # We explicitly ensure _debug is preserved as per user request
        persistence_data = scraped_data 
        if "_debug" in scraped_data:
            persistence_data["_debug"] = scraped_data["_debug"]

        # -- Debug Logging for User --
        task_logger.info(f"DEBUG - EXTRACTION RESULTS SUMMARY: {json.dumps(clean_result, indent=2)}")
        
        has_debug = "_debug" in scraped_data
        has_html = has_debug and "full_html" in scraped_data["_debug"]
        html_size = len(scraped_data["_debug"]["full_html"]) if has_html else 0
        task_logger.info(f"DEBUG - PERSISTENCE INFO: has_debug={has_debug}, has_html={has_html}, html_size={html_size}")
        
        # Verify persistence_data keys
        p_keys = list(persistence_data.keys())
        task_logger.info(f"DEBUG - PERSISTENCE DATA KEYS: {p_keys}")
        
        if result.get("status") == "success":
            task_logger.info(f"DEBUG - SUCCESSFUL EXTRACTION. Content Type: {clean_result.get('content_type')}")
            
        # Database persistence
        try:
            if SessionLocal is None:
                task_logger.error("No se pudo iniciar la persistencia: SessionLocal no está configurado (¿DATABASE_URL faltante?)")
            else:
                db: Session = SessionLocal()
                # 1. Buscar la solicitud original por task_id
                db_request = db.query(DBScrapeRequest).filter(DBScrapeRequest.task_id == task_id).first()
                
                if db_request:
                    task_logger.info(f"Guardando resultados en la BD para request_id: {db_request.id}")
                    
                    # 2. Actualizar estado de la solicitud
                    db_request.status = result.get("status")
                    db_request.updated_at = datetime.utcnow()
                    
                    # 3. Crear el resultado detallado
                    db_result = DBScrapeResult(
                        id=str(uuid.uuid4()),
                        content_type=clean_result.get("content_type"),
                        reactions=clean_result.get("metrics", {}).get("reactions", 0),
                        comments=clean_result.get("metrics", {}).get("comments", 0),
                        shares=clean_result.get("metrics", {}).get("shares", 0),
                        views=clean_result.get("metrics", {}).get("views", 0),
                        error=clean_result.get("error"),
                        scraped_at=datetime.fromisoformat(str(result.get("scraped_at"))),
                        raw_data=persistence_data,
                        full_html=persistence_data.get("_debug", {}).get("full_html"),
                        request_id=db_request.id
                    )
                    
                    db.add(db_result)
                    db.commit()
                    task_logger.info("Datos guardados exitosamente en la base de datos.")
                else:
                    task_logger.warning(f"No se encontró ScrapeRequest para task_id {task_id}")
                
                db.close()
        except Exception as db_err:
            task_logger.error(f"Error al guardar en base de datos: {db_err}")

        # Optional: Send the final result via webhook if configured (Legacy support)
        if WEBHOOK_URL:
            await send_webhook(clean_result, task_logger)

# --- FastAPI App ---
VERSION = "1.0.9-fixed"
app = FastAPI(title="Modular Social Scraper API", version=VERSION)

@app.get("/")
async def root():
    return {
        "name": "OBScrapping Backend",
        "version": VERSION,
        "status": "running",
        "server_time": datetime.utcnow().isoformat(),
        "documentation": "/docs"
    }

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
