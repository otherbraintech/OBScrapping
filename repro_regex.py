import re
import sys

def _normalize_count(value, text_context=None):
    if value is None: return None
    s = str(value).strip().replace(" ", "").lower()
    mult = 1
    if s.endswith('k'): mult = 1000; s = s[:-1]
    elif s.endswith('m'): mult = 1000000; s = s[:-1]
    s = s.replace(",", ".")
    try:
        if s.count('.') > 1:
            parts = s.split('.')
            s = "".join(parts[:-1]) + "." + parts[-1]
        return int(float(s) * mult)
    except: return None

patterns = [
    r">([\d.,]+[KMkm]?)\s*(?:views?|vues?|visualizaciones|reproducciones|plays?|visualizzazioni|visualizações)<",
    r"aria-label=\"([\d.,]+[KMkm]?)\s*(?:views?|vues?|visualizaciones|reproducciones|plays?)\"",
    r"\"text\"\s*:\s*\"([\d.,]+[KMkm]?)\s*(?:views?|vues?|visualizaciones|reproducciones|plays?|visualizzazioni|visualizações)\"",
]

test_html = [
    '>1,5 K vues<',
    'aria-label="1,5 K vues"',
    '"text":"1,5 K vues"'
]

for html in test_html:
    found = False
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            val = m.group(1)
            norm = _normalize_count(val)
            print(f"HTML: {html} | Pattern: {pat} | Found: '{val}' | Normalized: {norm}")
            found = True
            break
    if not found:
        print(f"HTML: {html} | FAILED TO MATCH")

# Improved pattern
improved_patterns = [
    r">([\d.,]+\s*[KMkm]?)\s*(?:views?|vues?|visualizaciones|reproducciones|plays?|visualizzazioni|visualizações)<",
    r"aria-label=\"([\d.,]+\s*[KMkm]?)\s*(?:views?|vues?|visualizaciones|reproducciones|plays?)\"",
    r"\"text\"\s*:\s*\"([\d.,]+\s*[KMkm]?)\s*(?:views?|vues?|visualizaciones|reproducciones|plays?|visualizzazioni|visualizações)\"",
]

print("\nTesting Improved Patterns:")
for html in test_html:
    found = False
    for pat in improved_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            val = m.group(1)
            norm = _normalize_count(val)
            print(f"HTML: {html} | Pattern: {pat} | Found: '{val}' | Normalized: {norm}")
            found = True
            break
    if not found:
        print(f"HTML: {html} | FAILED TO MATCH")
