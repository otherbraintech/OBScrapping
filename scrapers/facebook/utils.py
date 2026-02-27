import re
import html as _html
import unicodedata
from typing import Optional, Any

def _normalize_text(text: str) -> str:
    """Normalize text for reliable regex matching.
    Converts non-breaking spaces, middots and other unicode to plain ASCII equivalents."""
    if not text:
        return text
    # Decode HTML entities first
    text = _html.unescape(text)
    # Replace non-breaking space (\u00a0) and other whitespace variants with normal space
    text = text.replace('\u00a0', ' ').replace('\u2009', ' ').replace('\u202f', ' ')
    # Replace middot (·) with a space so patterns like '114 réactions · 17 partages' work
    text = text.replace('\u00b7', ' ').replace('\u2022', ' ')
    # Normalize unicode (NFC) and collapse multiple spaces
    text = unicodedata.normalize('NFC', text)
    text = re.sub(r'  +', ' ', text)
    return text.strip()

def _extract_shares_count_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    text = _normalize_text(text)
    patterns = [
        r"([\d.,]+\s*[KMkm]?)\s*(?:shares?|compartido|compartidos|veces compartido|partages?|condivisioni|compartilhamentos|repartages?)",
        r"([\d.,]+)\s*veces\s*(?:de\s*)?compartido",
        r"([\d.,]+\s*[KMkm]?)\s*fois\s*(?:de\s*)?partagé",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None

def _extract_reactions_count_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    text = _normalize_text(text)
    patterns = [
        r"(?:Tú|Usted|You|Usted,).*?(?:y\s*|and\s*)?([\d.,]+\s*[KMkm]?)\s*(?:personas?|others?)\s*(?:más|more)",
        r"(?:Todas las reacciones|Total reactions|Reacciones|Toutes les réactions):\s*([\d.,]+\s*[KMkm]?)",
        r"([\d.,]+\s*[KMkm]?)\s*(?:reactions?|reaccione?s|r[eé]actions?|reações|reazioni|personas reaccionaron)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None

def _extract_comments_count_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    text = _normalize_text(text)
    patterns = [
        r"view\s+all\s+([\d.,]+)\s*comments?",
        r"ver\s+los\s+([\d.,]+)\s*comentarios",
        r"([\d.,]+)\s*(?:comments?|comentarios|commentaires?|commenti|comentários)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None

def _extract_views_count_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    text = _normalize_text(text)
    patterns = [
        # Pattern 1: "1.2K views" or "7 241 vues"
        r"([\d][\d.,\s]*(?:[KMkm]|mil|mille|millones?|millón|million|mill|lectures?|visionnages?|replays?|visionnements?|bises?))\s*(?:de\s+)?(?:views?|visualizaciones|reproducciones|plays?|vistas|vues?|visualizzazioni|visualizações|visualisatio?ns?|reprod\.|lectures?|visionnages?|replays?|visionnements?|bises?)",
        # Pattern 2: "Views : 1 200" or "Vues: 1.2K" (handles space before colon)
        r"(?:views?|visualizaciones|reproducciones|plays?|vistas|vues?|visualizzazioni|visualizações|visualisatio?ns?|lectures?|visionnages?|replays?|visionnements?|bises?)\s*:\s*(?:de\s+)?([\d][\d.,\s]*(?:[KMkm]|mil|mille|millones?|millón|million|mill|lectures?|visionnages?|replays?|visionnements?|bises?)?)",
        r"([\d.,\s]+\s*[KMkm]?)\s*mil\s*(?:de\s+)?(?:visualizaciones|reproducciones|vistas|reprod\.)",
        r"([\d.,\s]+\s*[KMkm]?)\s*millones?\s*(?:de\s*)?(?:visualizaciones|reproducciones|vistas|reprod\.)",
        # Relaxed pattern for "N vues" or "N views" in HTML/JSON attributes
        r"([\d][\d\s.,]*[KMkm]?)\s*(?:views?|vues?|visualizaciones|reproducciones|vistas|reprod\.|lectures?|visionnages?|visionnements?|replays?|bises?)",
        # Very relaxed catch-all for anything that looks like "Number Vues" or "Number Plays"
        r"([\d][\d.,\s]*[KMkm]?)\s*(?:vues?|views?|plays?|reprod\.|lectures?|visionnages?|visionnements?|replays?|bises?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
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

    s = re.sub(r"\s+", "", s).lower()
    
    # Handle suffixes K, M, and word units
    mult = 1
    
    # Check for millions (longer words first)
    if any(s.endswith(x) for x in ['millones', 'million', 'millón', 'millon', 'mill']):
        mult = 1000000
        for x in ['millones', 'million', 'millón', 'millon', 'mill']:
            if s.endswith(x):
                s = s[:-len(x)]
                break
    elif any(s.endswith(x) for x in ['mil', 'mille']):
        mult = 1000
        for x in ['mil', 'mille']:
            if s.endswith(x):
                s = s[:-len(x)]
                break
    elif s.endswith('k'):
        mult = 1000
        s = s[:-1]
    elif s.endswith('m'):
        # M can be ambiguous (mil vs million), but usually million in English/French
        # If it was Spanish "mil", it would likely have matched above.
        mult = 1000000
        s = s[:-1]
    
    # Handle localized separators
    # French often uses spaces as thousand separators (e.g., "7 241")
    s = s.replace(",", ".").replace(" ", "")
    
    try:
        # If there are multiple dots now (from 1.234.567), keep only the last one for decimal
        if s.count('.') > 1:
            parts = s.split('.')
            s = "".join(parts[:-1]) + "." + parts[-1]
            
        num = float(s)
        return int(num * mult) + added_count
    except (ValueError, TypeError):
        # Last resort: just digits
        digits = re.sub(r"[^0-9]", "", s)
        if digits:
            return int(digits) + added_count
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
            r'"i18n_reaction_count"\s*:\s*"(\d+)',
        ],
        "comments": [
            r'"comment_count"\s*:\s*\{"total_count"\s*:\s*(\d+)',
            r'"comment_count"\s*:\s*(\d+)',
            r'"comments"\s*:\s*\{"total_count"\s*:\s*(\d+)',
            r'"comment_rendering_instance_count"\s*:\s*(\d+)',
            r'"total_comment_count"\s*:\s*(\d+)',
            r'"comment_count_reduced"\s*:\s*"(\d+)',
            r'"i18n_comment_count"\s*:\s*"(\d+)',
            r'"comments_count"\s*:\s*(\d+)',
            r'"commentCount"\s*:\s*(\d+)',
        ],
        "shares": [
            r'"share_count"\s*:\s*\{"count"\s*:\s*(\d+)',
            r'"share_count"\s*:\s*(\d+)',
            r'"reshare_count"\s*:\s*(\d+)',
            r'"i18n_share_count"\s*:\s*"(\d+)',
        ],
        "views": [
            r'"play_count"\s*:\s*(\d+)',
            r'"video_view_count"\s*:\s*(\d+)',
            r'"view_count"\s*:\s*(\d+)',
            r'"video_view_count_renderer"\s*:\s*\{"text"\s*:\s*\{"text"\s*:\s*"([\d.,\s]*[KMkm]?)',
            r'"seen_by_count"\s*:\s*\{"count"\s*:\s*(\d+)',
            r'"video_play_count"\s*:\s*(\d+)',
            r'"i18n_video_view_count"\s*:\s*"([\d.,\s]*[KMkm]?)',
            r'vue_count"\s*:\s*(\d+)',
            r'playCount"\s*:\s*(\d+)',
        ],
    }

    for field, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, html)
            if m:
                try:
                    raw_val = m.group(1)
                    # Use _normalize_count to handle K, M and localized separators correctly
                    normalized = _normalize_count(raw_val)
                    if normalized is not None:
                        result[field] = normalized
                        break
                except (ValueError, IndexError):
                    continue

    return result


def _extract_engagement_from_visible_text(html: str) -> dict:
    """
    Searches the raw HTML for visible-text engagement patterns.
    Facebook sometimes renders engagement counts as visible text outside JSON
    in formats like '48 commentaires', '1,2K vues', etc.
    """
    result = {}

    comment_patterns = [
        r'>([\d.,\s]*[KMkm]?)\s*(?:comments?|comentarios?|commentaires?|commenti|comentários)<',
        r'>([\d.,\s]*[KMkm]?)\s*(?:comments?|comentarios?|commentaires?|commenti|comentários)</span>',
        r'aria-label="([\d.,\s]*[KMkm]?)\s*(?:comments?|comentarios?|commentaires?|commenti|comentários)"',
        r'"text"\s*:\s*"([\d.,\s]*[KMkm]?)\s*(?:comments?|comentarios?|commentaires?|commenti|comentários)"',
    ]
    for pat in comment_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            result["comments"] = m.group(1)
            break

    # Look for views/plays count text patterns
    views_patterns = [
        r'>([\d.,\s]*[KMkm]?)\s*(?:de\s+)?(?:views?|vues?|visualizaciones|reproducciones|plays?|visualizzazioni|visualizações|visualisatio?ns?|lectures?|visionnages?|visionnements?)<',
        r'aria-label="([\d.,\s]*[KMkm]?)\s*(?:de\s+)?(?:views?|vues?|visualizaciones|reproducciones|plays?|visualisatio?ns?|lectures?|visionnages?|visionnements?)"',
        r'"text"\s*:\s*"([\d.,\s]*[KMkm]?)\s*(?:de\s+)?(?:views?|vues?|visualizaciones|reproducciones|plays?|visualizzazioni|visualizações|visualisatio?ns?|reprod\.|lectures?|visionnages?|visionnements?)[^"]*"',
    ]
    for pat in views_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            result["views"] = m.group(1)
            break

    return result


def _get_fb_image_signature(url: str) -> str:
    """
    Extracts a unique signature from a Facebook CDN image URL.
    Facebook URLs for the same image often share the same set of numeric IDs
    in the filename (e.g. [account_id]_[photo_id]_[misc]_n.jpg).
    """
    # Strip query params
    base = url.split('?')[0]
    # Get filename part
    filename = base.split('/')[-1]
    
    # Extract all numeric parts that look like IDs (length > 7)
    # This is more robust than just picking the first part
    ids = re.findall(r'(\d{8,})', filename)
    if ids:
        return ".".join(ids)
    
    # Fallback: if no long segments, take the whole filename without extension
    return re.sub(r'\.[a-z0-9]+$', '', filename, flags=re.IGNORECASE)

def _deduplicate_fb_images(urls: list[str]) -> list[str]:
    """Deduplicates Facebook image URLs by their unique signature (ID)."""
    seen_sigs = set()
    unique_urls = []
    for url in urls:
        sig = _get_fb_image_signature(url)
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            unique_urls.append(url)
    return unique_urls

def _extract_images_from_html(html: str) -> list:
    """
    Extracts all post image URLs from Facebook's inline GraphQL JSON blobs.
    Returns a deduplicated list of unique high-resolution photo URLs.
    Deduplication is done by image signature to avoid multiple resolutions.
    """
    images: list = []

    # We do a broad search: find every occurrence of scontent-* or scontent.* in the HTML
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

        # Skip tiny thumbnail sizes
        size_match = re.search(r'[sp](\d+)x(\d+)', url)
        if size_match:
            try:
                w = int(size_match.group(1))
                h = int(size_match.group(2))
                if w < 200 and h < 200:
                    continue
            except (ValueError, IndexError):
                pass

        # Skip profile images and UI elements
        skip_keywords = ["/safe_image/", "/cp/", "profile_pic", "emoji", "sticker", "static.xx.fbcdn.net"]
        if any(kw in url for kw in skip_keywords):
            continue

        # Normalize: strip trailing punctuation
        url = url.rstrip('.,;)')
        images.append(url)

    return _deduplicate_fb_images(images)


def _extract_reactions_count_from_html(html: str) -> Optional[str]:
    """Legacy wrapper — extracts just reaction count from HTML."""
    data = _extract_engagement_from_html(html)
    val = data.get("reactions")
    return str(val) if val else None
