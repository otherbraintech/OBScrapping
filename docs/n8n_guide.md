# Guía de Integración con n8n

Esta guía explica cómo integrar el scraper de Facebook con n8n para automatización de workflows.

## Arquitectura del Flujo

```
┌─────────────┐
│   n8n       │
│  Workflow   │
└──────┬──────┘
       │ 1. POST /scrape
       │    {url, webhook_url}
       ▼
┌─────────────┐
│  Scraper    │ ← Procesa en background
│    API      │
└──────┬──────┘
       │ 2. Callback webhook
       │    {task_id, data}
       ▼
┌─────────────┐
│   n8n       │
│  Webhook    │ ← Continúa workflow
└─────────────┘
```

## Setup en n8n

### Paso 1: Crear Webhook de Respuesta

1. Agregá un nodo **Webhook**
2. Configurá:
   - **HTTP Method**: POST
   - **Path**: `/facebook-scraper-response` (o cualquier path único)
   - **Authentication**: None (o Basic Auth si preferís)
3. **Guardá** el workflow para generar la URL del webhook
4. **Copiá la URL** (ej: `https://tu-n8n.com/webhook/abc123`)

### Paso 2: Crear HTTP Request al Scraper

1. Agregá un nodo **HTTP Request**
2. Configurá:

```json
{
  "method": "POST",
  "url": "https://tu-scraper.easypanel.host/scrape",
  "headers": {
    "Content-Type": "application/json"
  },
  "body": {
    "url": "={{ $json.facebook_url }}",
    "webhook_url": "https://tu-n8n.com/webhook/abc123"
  },
  "timeout": 120000
}
```

**Importante:** El timeout debe ser alto (120 segundos mínimo) aunque el scraper responde inmediatamente, para evitar issues de red.

### Paso 3: Conectar los Nodos

```
[Trigger] → [HTTP Request] → [Set Variable]
                              ↓
                          [Continue workflow...]

[Webhook] → [Process Data] → [Save to DB/Spreadsheet]
```

## Ejemplo Completo: Monitoreo de Posts

### Workflow n8n

1. **Schedule Trigger** (cada 1 hora)
2. **Get URLs from Spreadsheet** (Google Sheets con lista de posts)
3. **Loop over URLs**
   - **HTTP Request** a `/scrape` con webhook_url
4. **Webhook** recibe los datos
5. **Filter** posts con > 100 reacciones
6. **Update Spreadsheet** con datos actualizados
7. **Send Notification** (Discord/Slack) si hay posts virales

### Código del Nodo HTTP Request

```javascript
// Body (JSON)
{
  "url": "{{ $json.post_url }}",
  "webhook_url": "{{ $node.Webhook.context.webhookUrl }}"
}
```

### Procesamiento de Respuesta del Webhook

```javascript
// Function node para procesar data
const data = $input.item.json.data;

return {
  json: {
    author: data.author,
    caption: data.caption?.substring(0, 100) + "...",
    reactions: parseInt(data.reactions) || 0,
    shares: parseInt(data.shares) || 0,
    image_url: data.image,
    scraped_at: data.scraped_at,
    post_url: $input.item.json.url,
  },
};
```

## Testing con cURL

Antes de integrar con n8n, probá desde terminal:

```bash
curl -X POST https://tu-scraper.easypanel.host/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.facebook.com/USERNAME/posts/123456",
    "webhook_url": "https://webhook.site/unique-id"
  }'
```

Deberías recibir:

```json
{
  "task_id": "uuid-1234",
  "status": "processing"
}
```

Luego, en webhook.site vas a ver la respuesta con los datos extraídos.

## Manejo de Errores

### Error: "Timeout"

**Causa:** El scraper tardó más de lo esperado

**Solución:**

- Aumentá el timeout del HTTP Request node a 180 segundos
- Verificá los logs de EasyPanel para ver si está stuck en algún paso

### Error: "Webhook not received"

**Causa:** La URL del webhook no es accesible desde el scraper

**Solución:**

- Verificá que la URL del webhook sea pública (no localhost)
- Probá la URL con curl desde otro servidor
- Chequeá firewall o rate limiting en n8n

### Error: "Empty data returned"

**Causa:** Facebook bloqueó el scraper o la URL es inválida

**Solución:**

- Revisá logs de EasyPanel: buscar "DIAGNOSTIC" lines
- Verificá que el proxy esté configurado
- Intentá con otra URL de Facebook

### Error: "Task already processing"

**Causa:** Se envió el mismo request dos veces simultáneamente

**Solución:**

- Agregá un delay entre requests en el loop de n8n
- Implementá deduplicación por URL en n8n

## Best Practices

### 1. Rate Limiting

No hagas más de **10-20 requests por hora** para evitar bans de Facebook.

**En n8n:**

```javascript
// Delay node después del HTTP Request
await new Promise((resolve) => setTimeout(resolve, 180000)); // 3 minutos
```

### 2. Deduplicación

Guardá task_ids en una base de datos para evitar scrapes duplicados.

### 3. Retry Logic

Si el webhook falla, implementá retry automático:

```javascript
// HTTP Request node - Options
{
  "retry": {
    "maxRetries": 3,
    "retryInterval": 5000
  }
}
```

### 4. Logging

Guardá todos los task_ids y responses en Google Sheets o DB para debugging.

### 5. Notificaciones

Enviá notificaciones solo para casos importantes (errors, posts virales) para evitar spam.

## Webhook Payload Completo

```json
{
  "task_id": "3c7d2115-7012-4858-8032-ea74133773cb",
  "url": "https://www.facebook.com/...",
  "status": "success",
  "scraped_at": "2026-02-15T17:55:48.246954",
  "data": {
    "author": "Mario Cronenbold",
    "caption": "📍 Día 23 – Integración del Norte...",
    "description": "...",
    "reactions": "322",
    "shares": "40",
    "image": "https://...",
    "video_thumbnail": "https://...",
    "canonical_url": "https://...",
    "content_type": "video.other",
    "raw_og_data": {
      "og_title": "...",
      "og_description": "...",
      "og_image": "...",
      "og_url": "...",
      "og_type": "..."
    }
  },
  "error": null
}
```

Si hay error:

```json
{
  "task_id": "...",
  "url": "...",
  "status": "error",
  "scraped_at": "...",
  "data": null,
  "error": "Facebook redirected to login page - cookies expired"
}
```

## Casos de Uso

### 1. Monitoreo de Competencia

Scrapea posts de competidores cada 6 horas y notifica si tienen > 500 reacciones.

### 2. Análisis de Engagement

Recopila datos históricos de tus posts para calcular mejor horario de publicación.

### 3. Detección de Tendencias

Encuentra posts virales en tu nicho y analiza qué funcionó.

### 4. Reportes Automáticos

Genera reportes semanales de performance de redes sociales.

## Troubleshooting

Ver `troubleshooting.md` para problemas específicos del scraper.
