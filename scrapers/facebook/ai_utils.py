import os
import json
import httpx
import logging
import re
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("ai_utils")
logger.setLevel(logging.INFO)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-lite-preview-02-05:free")

async def extract_metrics_with_ai(html_content: str, url: str) -> Dict[str, Any]:
    """
    Uses OpenRouter AI to extract engagement metrics from Facebook Reel HTML content.
    """
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY not found in environment. Skipping AI extraction.")
        return {}

    # Clean HTML to reduce token usage
    # Keep meta tags and some specific structural elements that might contain metrics
    cleaned_html = _preprocess_html(html_content)
    
    prompt = f"""
    Eres un extractor de datos de alta precisión. Tu tarea es encontrar las métricas de compromiso (engagement) de este post de Facebook.
    
    Busca específicamente:
    1. Vistas (Views/Vues/Reproducciones/Visualizaciones).
    2. Reacciones (Likes/Reactions/Réactions/Me gusta).
    3. Comentarios (Comments/Commentaires).
    4. Compartidos (Shares/Partages/Veces compartido).

    IMPORTANTE:
    - Si el idioma es FRANCÉS, busca "vues" para vistas y "réactions" para reacciones.
    - Si el idioma es ESPAÑOL, busca "reproducciones" para vistas.
    - Las vistas a veces aparecen como "1,2 K vues" o "1M vues".
    - Si encuentras un número seguido de "vues" o "plays", eso SON las vistas.
    
    Responde ÚNICAMENTE con un objeto JSON en este formato:
    {{
      "views_count": número_entero,
      "reactions_count": número_entero,
      "comments_count": número_entero,
      "shares_count": número_entero,
      "confidence": 0-1,
      "source_summary": "breve resumen de dónde se encontró"
    }}
    
    Si no encuentras una métrica, pon 0.
    Contenido:
    {cleaned_html}
    """

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/otherbraintech/OBScrapping",
                    "X-OpenRouter-Title": "OBScrapping Facebook Metric Extractor",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a specialized scraper assistant. You extract structured data from messy HTML strings. Always return JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": { "type": "json_object" }
                }
            )
            
            if response.status_code != 200:
                logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
                return {}
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            metrics = json.loads(content)
            
            logger.info(f"AI Extraction success for {url}: {metrics}")
            return metrics

    except Exception as e:
        logger.error(f"Error in extract_metrics_with_ai: {e}")
        return {}

def _preprocess_html(html: str) -> str:
    """Extracts only potentially relevant parts of the HTML to save tokens."""
    # Keep <title>, <meta> tags, and any text that looks like a number near keywords
    relevant_tags = re.findall(r'<(title|meta|span|div)[^>]*>.*?</\1>|<meta[^>]*>', html, re.DOTALL | re.IGNORECASE)
    
    # Filter for keywords in the captured tags
    keywords = ["reacción", "reacciones", "reaction", "comment", "comentario", "share", "compartido", "partage", "view", "vista", "reproducción", "visualización"]
    filtered = []
    
    # Also keep meta tags regardless of keywords as they often have the clean data
    for tag in relevant_tags:
        if any(kw.lower() in tag.lower() for kw in keywords) or "og:" in tag.lower():
            # Strip some common noise from Facebook attributes
            tag = re.sub(r'class="[^"]*"', '', tag)
            tag = re.sub(r'style="[^"]*"', '', tag)
            filtered.append(tag)
            
    # Join and limit size (approx 4000 chars should be enough for metrics)
    return "\n".join(filtered)[:4000]
