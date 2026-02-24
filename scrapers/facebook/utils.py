import re
import html as _html
from typing import Optional, Any

def _extract_shares_count_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"([\d.,]+[KMkm]?)\s*(?:shares?|compartido|veces compartido)",
        r"([\d.,]+)\s*veces\s*compartido",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None

def _extract_reactions_count_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"(?:Tú|Usted|You|Usted,).*?(?:y\s*|and\s*)?([\d.,]+[KMkm]?)\s*(?:personas?|others?)\s*(?:más|more)",
        r"(?:Todas las reacciones|Total reactions|Reacciones):\s*([\d.,]+[KMkm]?)",
        r"([\d.,]+[KMkm]?)\s*(?:reactions?|reaccione?s|personas reaccionaron)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None

def _extract_comments_count_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"view\s+all\s+([\d.,]+)\s*comments?",
        r"ver\s+los\s+([\d.,]+)\s*comentarios",
        r"([\d.,]+)\s*(?:comments?|comentarios)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None

def _extract_views_count_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"([\d.,]+[KMkm]?)\s*(?:views?|visualizaciones|reproducciones|plays?|vistas)",
        r"([\d.,]+)\s*mil\s*(?:visualizaciones|reproducciones|vistas)",
        r"([\d.,]+)\s*millones\s*(?:de\s*)?(?:visualizaciones|reproducciones|vistas)",
        r"([\d.,]+)\s*thousand\s*(?:views?|plays?)",
        r"([\d.,]+)\s*million\s*(?:views?|plays?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None

def _normalize_count(value: Optional[str], text_context: Optional[str] = None) -> Optional[int]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    
    added_count = 0
    if text_context:
        t_low = text_context.lower()
        if any(kw in t_low for kw in ["tú y ", "usted y ", "you and "]):
            added_count = 1
        elif any(kw in t_low for kw in ["tú, ", "usted, ", "you, "]):
            added_count = 2

    s = s.replace(" ", "")
    m_mil = re.match(r"^(\d+(?:[\.,]\d+)?)mil$", s, re.IGNORECASE)
    if m_mil:
        num = float(m_mil.group(1).replace(",", "."))
        return int(num * 1000) + added_count
    
    m = re.match(r"^(\d+(?:[\.,]\d+)?)\s*([KkMm])$", s)
    if m:
        num = float(m.group(1).replace(",", "."))
        mult = 1000 if m.group(2).lower() == "k" else 1000000
        return int(num * mult) + added_count
    
    s_digits = re.sub(r"[^0-9]", "", s)
    if not s_digits:
        return None
    try:
        return int(s_digits) + added_count
    except Exception:
        return None

def _extract_engagement_from_html(html: str) -> dict:
    """
    Extracts engagement counts from Facebook's inline GraphQL JSON blobs.
    Facebook embeds data in <script> tags even for anonymous users.
    Returns a dict with any found counts: reactions, comments, shares, views.
    """
    result = {}

    # Patterns for JSON-embedded counts (from Facebook's GraphQL response JSONs)
    patterns = {
        "reactions": [
            r'"reaction_count"\s*:\s*\{"count"\s*:\s*(\d+)',
            r'"reaction_count"\s*:\s*(\d+)',
            r'"reactions"\s*:\s*\{"count"\s*:\s*(\d+)',
            r'"total_count"\s*:\s*(\d+).*?"reaction',
        ],
        "comments": [
            r'"comment_count"\s*:\s*(\d+)',
            r'"comments"\s*:\s*\{"total_count"\s*:\s*(\d+)',
            r'"comment_rendering_instance_count"\s*:\s*(\d+)',
        ],
        "shares": [
            r'"share_count"\s*:\s*\{"count"\s*:\s*(\d+)',
            r'"share_count"\s*:\s*(\d+)',
            r'"reshare_count"\s*:\s*(\d+)',
        ],
        "views": [
            r'"play_count"\s*:\s*(\d+)',
            r'"video_view_count"\s*:\s*(\d+)',
            r'"view_count"\s*:\s*(\d+)',
        ],
    }

    for field, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, html)
            if m:
                try:
                    result[field] = int(m.group(1))
                    break
                except (ValueError, IndexError):
                    continue

    return result


def _extract_images_from_html(html: str) -> list:
    """
    Extracts all post image URLs from Facebook's inline GraphQL JSON blobs.

    Facebook embeds media data (including ALL gallery images) in <script> tags
    even for unauthenticated users. The DOM may only show 1 image grid tile,
    but all image URIs are present in the JSON payload.

    Returns a deduplicated list of unique high-resolution fbcdn image URLs.
    """
    seen: set = set()
    images: list = []

    # Facebook encodes image URIs in JSON in multiple formats.
    # Pattern logic: find any "uri" followed by an fbcdn URL that looks like a photo
    uri_patterns = [
        # Standard: "uri":"https://scontent...fbcdn.net/...jpg..."
        r'"uri"\s*:\s*"(https://[^"]+\.fbcdn\.net/[^"]+\.(?:jpg|png|webp)[^"]*)"',
        # Sometimes the key is "src"
        r'"src"\s*:\s*"(https://[^"]+\.fbcdn\.net/[^"]+\.(?:jpg|png|webp)[^"]*)"',
        # Image objects with dimensions
        r'"image"\s*:\s*\{"uri"\s*:\s*"(https://[^"]+\.fbcdn\.net/[^"]+\.(?:jpg|png|webp)[^"]*)"',
        # Thumbnail/large_image wrappers
        r'"large_image"\s*:\s*\{"uri"\s*:\s*"(https://[^"]+\.fbcdn\.net/[^"]+\.(?:jpg|png|webp)[^"]*)"',
        r'"full"\s*:\s*\{"uri"\s*:\s*"(https://[^"]+\.fbcdn\.net/[^"]+\.(?:jpg|png|webp)[^"]*)"',
    ]

    for pat in uri_patterns:
        for m in re.finditer(pat, html):
            raw_url = m.group(1)
            # Unescape JSON-encoded backslashes (e.g. \u0026 -> &, \/ -> /)
            url = raw_url.replace("\\/", "/")
            try:
                url = _html.unescape(url)
            except Exception:
                pass

            # Skip profile / avatar images (they are very small and in /safe_image/ paths)
            skip_keywords = ["/safe_image/", "/profile", "/cp/", "emoji", "icon", "sticker", "logo"]
            if any(kw in url for kw in skip_keywords):
                continue

            # Skip very small thumbnails that appear in "thumbnail" fields
            # These typically have small dimensions encoded in the URL path (s40x40, p40x40, etc.)
            if re.search(r'[sp]\d{2}x\d{2}', url):
                continue

            if url not in seen:
                seen.add(url)
                images.append(url)

    return images


def _extract_reactions_count_from_html(html: str) -> Optional[str]:
    """Legacy wrapper — extracts just reaction count from HTML."""
    data = _extract_engagement_from_html(html)
    val = data.get("reactions")
    return str(val) if val else None
