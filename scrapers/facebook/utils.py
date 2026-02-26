import re
import html as _html
from typing import Optional, Any

def _extract_shares_count_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"([\d.,]+\s*[KMkm]?)\s*(?:shares?|compartido|veces compartido|partages?|condivisioni|compartilhamentos)",
        r"([\d.,]+)\s*veces\s*compartido",
        r"([\d.,]+\s*[KMkm]?)\s*fois\s*partagé",
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
        r"(?:Tú|Usted|You|Usted,).*?(?:y\s*|and\s*)?([\d.,]+\s*[KMkm]?)\s*(?:personas?|others?)\s*(?:más|more)",
        r"(?:Todas las reacciones|Total reactions|Reacciones|Toutes les réactions):\s*([\d.,]+\s*[KMkm]?)",
        r"([\d.,]+\s*[KMkm]?)\s*(?:reactions?|reaccione?s|réactions?|reações|reazioni|personas reaccionaron)",
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
        r"([\d.,]+\s*[KMkm]?)\s*(?:views?|visualizaciones|reproducciones|plays?|vistas|vues?|visualizzazioni|visualizações|reprod\.)",
        r"(?:views?|visualizaciones|reproducciones|plays?|vistas|vues?|visualizzazioni|visualizações):\s*([\d.,]+\s*[KMkm]?)",
        r"([\d.,]+\s*[KMkm]?)\s*mil\s*(?:visualizaciones|reproducciones|vistas|reprod\.)",
        r"([\d.,]+\s*[KMkm]?)\s*millones?\s*(?:de\s*)?(?:visualizaciones|reproducciones|vistas|reprod\.)",
        r"([\d.,]+\s*[KMkm]?)\s*mille\s*(?:vues?)",
        r"([\d.,]+\s*[KMkm]?)\s*thousand\s*(?:views?|plays?)",
        r"([\d.,]+\s*[KMkm]?)\s*million\s*(?:views?|plays?)",
        r"([\d.,]+\s*[KMkm]?)\s*vistos?",
        r"(?:再生回数|reproductions|reproduce|vues)\s*:\s*([\d.,]+\s*[KMkm]?)",
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

    s = re.sub(r"\s+", "", s).lower()
    
    # Handle suffixes K, M
    mult = 1
    if s.endswith('k'):
        mult = 1000
        s = s[:-1]
    elif s.endswith('m'):
        mult = 1000000
        s = s[:-1]
    
    # Handle localized separators
    # Case "1.5" or "1,5" -> float. Deciding which is decimal is tricky.
    # Usually if there is only one dot/comma and it's near the end, it's decimal.
    # But for simplicity, we treat both as possible decimals if smaller than 1000.
    s = s.replace(",", ".")
    
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
        r'>([\d.,\s]*[KMkm]?)\s*(?:views?|vues?|visualizaciones|reproducciones|plays?|visualizzazioni|visualizações)<',
        r'aria-label="([\d.,\s]*[KMkm]?)\s*(?:views?|vues?|visualizaciones|reproducciones|plays?)"',
        r'"text"\s*:\s*"([\d.,\s]*[KMkm]?)\s*(?:views?|vues?|visualizaciones|reproducciones|plays?|visualizzazioni|visualizações)"',
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
