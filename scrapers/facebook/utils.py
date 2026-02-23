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

def _extract_reactions_count_from_html(html: str) -> Optional[str]:
    # Placeholder for the complex HTML/regex parsing
    m = re.search(r'([\d,.]+)\s*(?:reacciones|reactions)', html, re.IGNORECASE)
    return m.group(1) if m else None
