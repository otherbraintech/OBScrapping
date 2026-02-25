import re
import html as _html
from typing import Optional, Any

def _extract_shares_count_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"([\d.,]+[KMkm]?)\s*(?:shares?|compartido|veces compartido|partages?|condivisioni|compartilhamentos)",
        r"([\d.,]+)\s*veces\s*compartido",
        r"([\d.,]+)\s*fois\s*partagé",
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
        r"(?:Todas las reacciones|Total reactions|Reacciones|Toutes les réactions):\s*([\d.,]+[KMkm]?)",
        r"([\d.,]+[KMkm]?)\s*(?:reactions?|reaccione?s|réactions?|reações|reazioni|personas reaccionaron)",
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
        r"([\d.,]+)\s*(?:comments?|comentarios|commentaires?|commenti|comentários)",
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
        r"([\d.,]+[KMkm]?)\s*(?:views?|visualizaciones|reproducciones|plays?|vistas|vues?|visualizzazioni|visualizações)",
        r"([\d.,]+)\s*mil\s*(?:visualizaciones|reproducciones|vistas)",
        r"([\d.,]+)\s*millones\s*(?:de\s*)?(?:visualizaciones|reproducciones|vistas)",
        r"([\d.,]+)\s*mille\s*(?:vues?)",
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

    Key insight from debugging:
    - Facebook embeds React state with photo data deep in the 1MB+ HTML
    - Photo CDN uses scontent-*.fbcdn.net or scontent.*.fbcdn.net 
    - UI/icon CDN uses static.xx.fbcdn.net (must be EXCLUDED)
    - JSON strings use escaped forward slashes: https:\/\/scontent-...
    - Thumbnails have size params like s150x150 or p100x100 in the URL

    Returns a deduplicated list of unique high-resolution photo URLs.
    """
    seen: set = set()
    images: list = []

    # We do a broad search: find every occurrence of scontent-* or scontent.* in the HTML
    # These are photo CDN URLs, distinct from static.xx.fbcdn.net which is UI/icons
    # Pattern handles both escaped (JSON) and unescaped (HTML attrs) forms
    broad_pattern = re.compile(
        r'https?:\\?/\\?/scontent[^"\'<>\s]+'
        r'\.(?:jpg|jpeg|png|webp)'
        r'[^"\'<>\s]*',
        re.IGNORECASE
    )

    for m in broad_pattern.finditer(html):
        raw_url = m.group(0)

        # Unescape JSON-encoded slashes: https:\/\/ -> https://
        url = raw_url.replace("\\/", "/")

        # Unescape HTML entities: &amp; -> &
        try:
            url = _html.unescape(url)
        except Exception:
            pass

        # Skip tiny thumbnail sizes (Facebook encodes sizes like s40x40, p100x100, s75x75)
        # BUT s600x600 is a real image — only skip if BOTH dimensions are under 200px
        size_match = re.search(r'[sp](\d+)x(\d+)', url)
        if size_match:
            w = int(size_match.group(1))
            h = int(size_match.group(2))
            if w < 200 and h < 200:
                continue

        # Skip profile images
        skip_keywords = ["/safe_image/", "/cp/", "profile_pic", "emoji", "sticker"]
        if any(kw in url for kw in skip_keywords):
            continue

        # Normalize: strip trailing punctuation that might bleed in from HTML context
        url = url.rstrip('.,;)')

        if url not in seen:
            seen.add(url)
            images.append(url)

    return images


def _extract_reactions_count_from_html(html: str) -> Optional[str]:
    """Legacy wrapper — extracts just reaction count from HTML."""
    data = _extract_engagement_from_html(html)
    val = data.get("reactions")
    return str(val) if val else None
