# Resumen del Proyecto - Facebook Scraper

## Descripción General

API de scraping de Facebook construida con **FastAPI** + **Playwright** que extrae datos de posts y Reels de Facebook de forma automatizada. Diseñada para integrarse con **n8n** u otros sistemas de automatización.

## Arquitectura

```
┌─────────────┐
│    n8n      │ ← Workflow automation
└──────┬──────┘
       │ HTTP POST
       ▼
┌─────────────────────┐
│  FastAPI Server     │ ← API endpoint (/scrape)
│  main.py            │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│  Playwright         │ ← Headless browser
│  + Stealth          │
│  + Proxy support    │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│  Proxy Residencial  │ ← DataImpulse proxy
│  (Bypass Cloudflare)│
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│    Facebook         │ ← Target site
└─────────────────────┘
```

## Stack Tecnológico

- **FastAPI**: Framework web asíncrono para el API endpoint
- **Playwright**: Headless browser automation (Chromium)
- **playwright-stealth**: Evasión de detección anti-bot
- **Proxy Residencial**: DataImpulse para bypass de Cloudflare
- **Python 3.12**: Runtime
- **Docker**: Containerización para deployment
- **EasyPanel**: Hosting platform

## Componentes Principales

### 1. API Endpoint (`/scrape`)

**Request:**

```json
{
  "url": "https://www.facebook.com/post/123456",
  "webhook_url": "https://your-n8n.com/webhook/abc"
}
```

**Response (Inmediata):**

```json
{
  "task_id": "uuid-1234",
  "status": "processing"
}
```

**Webhook Callback (Asíncrono):**

```json
{
  "task_id": "uuid-1234",
  "url": "https://...",
  "status": "success",
  "data": {
    "author": "Mario Cronenbold",
    "caption": "...",
    "reactions": "322",
    "shares": "40",
    "image": "https://...",
    ...
  }
}
```

### 2. Scraping Engine

**Estrategia Multi-Capa:**

1. **OpenGraph Meta Tags** (Capa principal, más confiable)
   - `og:title`, `og:description`, `og:image`, `og:video`
   - Facebook los expone públicamente para sharing

2. **Parsing de OG Title**
   - Regex para extraer: `"322 reactions · 40 shares | Caption | Author"`

3. **JavaScript Evaluation** (Fallback)
   - Evalúa `aria-label` attributes
   - Patrones en español: `"Me gusta: 263 personas"`, `"16 comentarios"`

4. **Page Body Regex** (Fallback)
   - Texto visible en la página
   - Patrones: `"38 veces compartido"`, `"5,5 mil visualizaciones"`

5. **DOM Selectors** (Fallback final)
   - CSS selectors para username, caption, etc.

### 3. Anti-Detección

**Técnicas implementadas:**

- ✅ **User-Agent aleatorio** — Pool de 10+ UAs realistas
- ✅ **Viewport aleatorio** — Diferentes resoluciones
- ✅ **Playwright Stealth** — Evita `navigator.webdriver` detection
- ✅ **Random delays** — Entre 3-10 segundos
- ✅ **Human-like scrolling** — 5 scrolls graduales + scroll completo
- ✅ **Mouse movements** — Movimientos aleatorios
- ✅ **Proxy residencial** — IP residencial vs. datacenter
- ✅ **Device fingerprinting** — `device_scale_factor`, `has_touch`

### 4. Sistema de Logging

**Niveles:**

- `INFO` — Progreso normal (navegación, parsing exitoso)
- `WARNING` — Problemas recuperables (timeout, login wall)
- `ERROR` — Failures críticos (parsing failed, Cloudflare block)

**Storage:**

- Logs timestampeados por task_id
- Accesibles desde EasyPanel Logs tab

### 5. Webhook System

**Diseño asíncrono:**

1. User hace POST a `/scrape`
2. API devuelve `task_id` inmediatamente (200 OK)
3. Scraping ocurre en background
4. Al completar, envía resultado a `webhook_url` vía httpx POST

**Ventajas:**

- No timeout en requests largos (scraping puede tardar 30-60 seg)
- n8n puede continuar workflow sin esperar
- Retry automático en webhooks (httpx timeout 30s)

## Datos Extraídos

### ✅ Actualmente Disponibles

```python
{
    "author": str,           # Nombre del autor
    "caption": str,          # Caption completo del post/reel
    "description": str,      # Descripción (truncada)
    "reactions": str,        # Total reacciones ("322")
    "shares": str,           # Total shares ("40")
    "image": str,            # URL de imagen/thumbnail
    "video_thumbnail": str,  # URL del video thumbnail
    "canonical_url": str,    # URL canónica de Facebook
    "content_type": str,     # "video.other", "article", etc.
    "raw_og_data": dict      # Todos los OG tags raw
}
```

### ❌ No Disponibles (Requieren Login + Bypass Avanzado)

- `comments` — Conteo de comentarios
- `views` — Conteo de visualizaciones
- `video_url` — URL directa del video

**Razón:** Facebook solo muestra estos datos a usuarios logueados, y combinar cookies + proxy puede triggear security checkpoints.

## Configuración Actual

### Variables de Entorno (EasyPanel)

```bash
# Proxy (Requerido para bypass de Cloudflare)
PROXY_HOST=gw.dataimpulse.com
PROXY_PORT=823
PROXY_USERNAME=...
PROXY_PASSWORD=...

# Cookies de Facebook (Opcionales, pueden causar checkpoints)
FB_COOKIE_C_USER=...
FB_COOKIE_XS=...
FB_COOKIE_DATR=...
FB_COOKIE_FR=...
FB_COOKIE_SB=...
```

## Performance

- **Tiempo promedio por scrape:** 25-40 segundos
- **Success rate:** ~95% para URLs públicas
- **Timeout:** 60 segundos para navigation
- **Memory:** ~300MB por instancia de Chromium
- **Concurrencia:** 1 scrape a la vez (single worker)

## Limitaciones Conocidas

1. **URLs cortas** — Las URLs de formato `/share/r/XXX/` pueden no funcionar bien. Preferir URLs completas.
2. **Posts privados** — No se pueden scrapear posts de perfiles privados o grupos cerrados
3. **Rate limiting** — Facebook puede rate-limitear después de ~100 requests/hora desde la misma IP
4. **Cloudflare updates** — Requiere mantenimiento si Cloudflare actualiza detección

## Alternativas Consideradas

| Solución                               | Pro                                 | Contra                        | Decisión      |
| -------------------------------------- | ----------------------------------- | ----------------------------- | ------------- |
| **facebook-scraper lib**               | Fácil setup                         | Broken en 2026, no mantenido  | ❌            |
| **Selenium + undetected-chromedriver** | Mejor anti-detección                | Requiere rewrite completo     | ❌            |
| **Graph API oficial**                  | Confiable, legal                    | Requiere app approval         | ⚠️ Futuro     |
| **Playwright + Proxy**                 | Balance funcionalidad/confiabilidad | Costo de proxy ($100-300/mes) | ✅ **Actual** |

## Roadmap

Ver `scalability_roadmap.md` para planes de escalabilidad (10 → 10k requests/día).
