# Guía de Troubleshooting

## Problemas Comunes y Soluciones

### 1. "raw_og_data: {}" - Datos Vacíos

**Síntomas:**

- El webhook devuelve `data: { raw_og_data: {} }`
- Logs muestran: `JS extraction found: 0 aria-labels, 0 engagement texts`
- Page Title es solo "Facebook"

**Causas posibles:**

#### A. URL Inválida o Formato Incorrecto

**URLs problemáticas:**

- ❌ `/share/r/XXXXX/` (URLs cortas)
- ❌ URLs de posts eliminados
- ❌ URLs de perfiles privados

**Solución:** Usá URLs completas:

```
✅ https://www.facebook.com/USERNAME/posts/1234567890
✅ https://www.facebook.com/USERNAME/videos/1234567890
✅ https://www.facebook.com/reel/1234567890
```

#### B. Security Checkpoint de Facebook

**Logs mostrarán:**

```
DIAGNOSTIC - Final URL: https://www.facebook.com/checkpoint/...
Facebook redirected to security checkpoint
```

**Solución:**

1. Remové las cookies de Facebook (desactivá FB*COOKIE*\* env vars)
2. Scrapea solo con proxy (datos públicos solamente)
3. O obtené cookies frescas de una sesión nueva

#### C. Cookies Expiradas

**Logs mostrarán:**

```
DIAGNOSTIC - Final URL: https://www.facebook.com/login/...
Facebook redirected to login page
```

**Solución:**

1. Obtené nuevas cookies de tu sesión actual de Facebook
2. Actualizá las env vars en EasyPanel
3. Redesplegá

#### D. Post Protegido/Privado

Si el post es de un perfil privado o grupo cerrado, Facebook no muestra OG tags públicamente.

**Solución:** Solo podés scrapear contenido público.

### 2. "Cloudflare WARP HTML ERROR"

**Síntomas:**

- HTML preview muestra "Cloudflare" en los logs
- HTML length < 5000 bytes
- Page title contiene "Cloudflare"

**Causa:** Proxy no configurado o inválido

**Solución:**

1. Verificá que las env vars del proxy estén configuradas:

   ```bash
   PROXY_HOST=gw.dataimpulse.com
   PROXY_PORT=823
   PROXY_USERNAME=...
   PROXY_PASSWORD=...
   ```

2. Chequeá los logs para confirmar:

   ```
   Using proxy: gw.dataimpulse.com:823
   ```

3. Si no ves esa línea → env vars no están configuradas

4. Verificá credenciales de DataImpulse:
   - ¿La cuenta tiene crédito?
   - ¿Las credenciales son correctas?

### 3. "Navigation Timeout"

**Síntomas:**

```
Navigation timed out, trying to proceed anyway...
```

**Causa:** Facebook tarda mucho en cargar o hay issues de red

**Solución:**

- El scraper automáticamente continúa después del timeout
- Si esto pasa frecuentemente, puede ser problema del proxy
- Contactá a DataImpulse para verificar performance del proxy

### 4. "Webhook Delivery Failed"

**Síntomas:**

- El scrape completa exitosamente en logs
- Pero n8n nunca recibe el webhook

**Causas:**

#### A. Webhook URL Inválida

**Solución:**

- Verificá que la URL del webhook sea pública (no localhost)
- Testea la URL con curl:
  ```bash
  curl -X POST https://tu-webhook-url \
    -H "Content-Type: application/json" \
    -d '{"test": "data"}'
  ```

#### B. Firewall/Rate Limiting

**Solución:**

- Chequeá firewall de n8n
- Verificá rate limiting en EasyPanel o n8n

#### C. Timeout en httpx

**Logs mostrarán:**

```
HTTP Request: POST https://... timed out
```

**Solución:**

- El scraper tiene timeout de 30s para webhooks
- Si n8n es lento, aumentá timeout en `main.py` (línea `httpx.post(..., timeout=30)`)

### 5. "Port Already in Use"

**Síntomas:**

```
[Errno 98] Address already in use
```

**Causa:** Otra instancia está corriendo en el mismo puerto

**Solución:**

1. En local: `kill` el proceso anterior
2. En EasyPanel: Redeployá el servicio (auto-maneja puertos)

### 6. "Chromium Executable Doesn't Exist"

**Síntomas:**

```
Executable doesn't exist at /path/to/chromium
```

**Causa:** Playwright browsers no instalados

**Solución:**

1. Verificá el `Dockerfile`:

   ```dockerfile
   RUN playwright install chromium
   ```

2. Si estás corriendo localmente:
   ```bash
   playwright install chromium
   ```

### 7. Proxy Connection Failed

**Síntomas:**

```
Error connecting to proxy: Connection refused
```

**Causas:**

- Credenciales incorrectas
- Cuenta de DataImpulse sin crédito
- Proxy temporalmente down

**Solución:**

1. Verificá credenciales en DataImpulse dashboard
2. Chequeá balance de la cuenta
3. Probá el proxy manualmente:
   ```bash
   curl -x http://USERNAME:PASSWORD@gw.dataimpulse.com:823 https://ipinfo.io
   ```

### 8. Memory Issues / Container Crashed

**Síntomas:**

- Container se reinicia constantemente
- Out of Memory errors

**Causa:** Chromium consume ~300MB por instancia

**Solución:**

1. Aumentá memoria del container en EasyPanel (mínimo 512MB)
2. Limitá requests concurrentes (actualmente: 1 a la vez)

## Diagnostic Checklist

Cuando algo no funciona, seguí estos pasos:

### 1. Revisá Logs de EasyPanel

Buscá estas líneas clave:

```
✅ Using proxy: gw.dataimpulse.com:823
✅ Facebook cookies found, injecting into browser context...
✅ Injected 5 Facebook cookies successfully
✅ Navigating to page...
✅ DIAGNOSTIC - Page Title: [título del post]
✅ DIAGNOSTIC - HTML Length: [> 100000 bytes]
❌ DIAGNOSTIC - Final URL: https://www.facebook.com/checkpoint/
❌ JS extraction found: 0 aria-labels
```

### 2. Verificá Variables de Entorno

```bash
# En EasyPanel → Environment tab
PROXY_HOST=...          # ✅ Set?
PROXY_PORT=...          # ✅ Set?
PROXY_USERNAME=...      # ✅ Set?
PROXY_PASSWORD=...      # ✅ Set?

FB_COOKIE_C_USER=...    # ⚠️ Opcional
FB_COOKIE_XS=...        # ⚠️ Opcional
# etc.
```

### 3. Test con URL Conocida

Probá con un post público popular que sabés que existe:

```bash
curl -X POST https://tu-scraper/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.facebook.com/zuck/posts/[alguna-id-valida]",
    "webhook_url": "https://webhook.site/unique-id"
  }'
```

### 4. Revisá Screenshot (si está disponible)

Los logs guardan screenshots en `/tmp/fb_debug_*.png`:

```bash
# SSH al container de EasyPanel
ls /tmp/fb_debug_*.png
```

Descargá y revisá qué página muestra Facebook.

### 5. Revisá HTML Preview en Logs

```
DIAGNOSTIC - HTML Preview: <!DOCTYPE html>...
```

Buscá keywords:

- ✅ `og:title`, `og:description` → Bueno, tiene OG tags
- ❌ `checkpoint`, `security` → Facebook pidiendo verificación
- ❌ `login`, `password` → Cookies expiradas
- ❌ `cloudflare` → Proxy no funcionando

## Contacto y Soporte

- **Logs no hacen sentido?** Compartí el task_id y los logs completos
- **Problema de proxy?** Contactá a DataImpulse support
- **Bug del código?** Abrí un issue en el repo GitHub

## Recursos Útiles

- `project_overview.md` — Arquitectura del sistema
- `proxy_setup.md` — Setup de proxy
- `facebook_cookies_setup.md` — Setup de cookies
- `deployment_guide.md` — Deploy en EasyPanel
