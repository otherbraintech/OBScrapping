# Guía de Deployment

## ¿Por qué NO Vercel?

Vercel **NO soporta** aplicaciones que requieren:

- Headless browsers (Playwright/Puppeteer)
- Procesos de larga duración (>10 segundos)
- Instalación de binarios de sistema (Chromium)

Nuestro scraper necesita las 3 cosas arriba, por lo tanto **Vercel no es compatible**.

## Plataformas Compatibles

### ✅ EasyPanel (Recomendado)

**Ventajas:**

- Docker nativo
- Soporte completo de Playwright
- Variables de entorno fáciles
- Logs en tiempo real
- Auto-deploy desde GitHub
- Precio razonable

**Setup:**

1. **Creá un nuevo servicio** en EasyPanel
2. **Conectá tu repositorio de GitHub**
3. **Configurá variables de entorno:**

   ```bash
   # Proxy (Requerido)
   PROXY_HOST=gw.dataimpulse.com
   PROXY_PORT=823
   PROXY_USERNAME=...
   PROXY_PASSWORD=...

   # Cookies de Facebook (Opcionales)
   FB_COOKIE_C_USER=...
   FB_COOKIE_XS=...
   FB_COOKIE_DATR=...
   FB_COOKIE_FR=...
   FB_COOKIE_SB=...
   ```

4. **Configurá el puerto:** 80 (EasyPanel maneja el routing)
5. **Deploy**

EasyPanel detectará automáticamente el `Dockerfile` y usará esa configuración.

### ✅ Railway

**Ventajas:**

- Similar a EasyPanel
- Free tier generoso
- Auto-deploy desde GitHub

**Setup:**

1. Importá el repo desde GitHub
2. Railway detecta el Dockerfile automáticamente
3. Agregá las variables de entorno (mismo que EasyPanel)
4. Deploy

### ✅ Render

**Ventajas:**

- Free tier disponible
- Docker support

**Desventajas:**

- Free tier tiene spin-down (instancia se apaga después de 15min inactiva)
- Puede ser lento para scraping

**Setup:**

1. New Web Service → Docker
2. Conectá GitHub repo
3. Configurá env vars
4. Deploy

### ✅ DigitalOcean App Platform

**Ventajas:**

- Confiable
- Escalable
- Buen soporte de Docker

**Desventajas:**

- No free tier
- ~$5-12/mes mínimo

## Dockerfile Explicado

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /app

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Instalar Playwright browsers
RUN playwright install chromium

# Puerto
EXPOSE 80

# Comando de inicio
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
```

**Puntos clave:**

- Usa imagen base de Playwright (ya tiene Chromium dependencies)
- Puerto 80 (configurable en EasyPanel)
- `playwright install chromium` instala el browser binario

## Environment Variables

### Requeridas

```bash
PROXY_HOST=gw.dataimpulse.com
PROXY_PORT=823
PROXY_USERNAME=...
PROXY_PASSWORD=...
```

Sin estas, Cloudflare bloqueará las requests.

### Opcionales

```bash
FB_COOKIE_C_USER=...       # Solo si querés intentar scraping con login
FB_COOKIE_XS=...           # Puede triggear security checkpoints
FB_COOKIE_DATR=...         # Ver facebook_cookies_setup.md
FB_COOKIE_FR=...
FB_COOKIE_SB=...
```

## Verificación Post-Deploy

1. **Check health endpoint:**

   ```bash
   curl https://tu-dominio.easypanel.host/
   ```

   Debería devolver: `{"message": "Facebook Scraper API", "status": "running"}`

2. **Revisá logs:**
   - EasyPanel: Logs tab
   - Railway: Deployment logs
   - Buscar línea: `Uvicorn running on http://0.0.0.0:80`

3. **Test scrape:**
   Desde n8n o Postman:

   ```bash
   POST https://tu-dominio/scrape
   {
     "url": "https://www.facebook.com/...",
     "webhook_url": "https://webhook.site/..."
   }
   ```

4. **Verificá proxy en logs:**
   Deberías ver: `Using proxy: gw.dataimpulse.com:823`

## Troubleshooting

### "Chromium executable doesn't exist"

- Ejecutar: `playwright install chromium` en el Dockerfile
- Asegurate de usar imagen base de Playwright

### "Cannot connect to proxy"

- Variables de entorno mal configuradas
- Credenciales de DataImpulse inválidas/expiradas

### "Port 8000 is already in use"

- Cambiar `--port 80` en el CMD del Dockerfile
- Configurar puerto correcto en EasyPanel

### Timeouts en scraping

- Aumentar timeout en n8n HTTP Request node (120 segundos mínimo)
- Verificar que el webhook_url sea accesible desde el servidor

## Costos Estimados

| Plataforma       | Costo/Mes | Notas                         |
| ---------------- | --------- | ----------------------------- |
| **EasyPanel**    | $5-15     | Depende del plan              |
| **Railway**      | $0-10     | Free tier hasta 500 horas/mes |
| **Render**       | $0-7      | Free tier con limitaciones    |
| **DigitalOcean** | $12+      | Sin free tier                 |
| **Proxies**      | $100-300  | DataImpulse o similar         |

**Total:** ~$105-315/mes (mayormente por proxies)

## Auto-Deploy Setup

### GitHub Actions (Opcional)

Si querés CI/CD automático:

```yaml
# .github/workflows/deploy.yml
name: Deploy to EasyPanel

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Trigger EasyPanel Deploy
        run: |
          curl -X POST https://easypanel.host/api/deploy \
            -H "Authorization: Bearer ${{ secrets.EASYPANEL_TOKEN }}"
```

Pero EasyPanel ya tiene auto-deploy nativo más simple.

## Respaldo y Rollback

- EasyPanel guarda últimas 10 deployments
- Podes hacer rollback con un click
- GitHub también sirve como backup del código
