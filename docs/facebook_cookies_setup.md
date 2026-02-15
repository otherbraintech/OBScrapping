# Configuración de Cookies de Facebook

Para obtener datos completos de engagement (incluyendo comentarios y visualizaciones en el futuro), el scraper puede usar cookies de Facebook para acceder como usuario logueado.

## ⚠️ Importante: Requiere Proxy Residencial

Las cookies de Facebook **solo funcionan con proxy residencial**. Sin proxy, Cloudflare detecta que las cookies se usan desde otra IP y bloquea la request.

**Setup requerido:**

1. ✅ Proxy residencial configurado (ver `proxy_setup.md`)
2. ✅ Cookies de Facebook (esta guía)

## Paso 1: Obtener tus Cookies de Facebook

### Método 1: Extensión EditThisCookie (Recomendado)

1. Instalá [EditThisCookie](https://chrome.google.com/webstore/detail/editthiscookie) en Chrome
2. Abrí Facebook y logueate
3. Hacé click en el ícono de EditThisCookie
4. Exportá las cookies (botón de exportar)
5. Copiá los valores de estas cookies:
   - **c_user** — Tu user ID numérico de Facebook
   - **xs** — Token de sesión (string largo)
   - **datr** — Token de dispositivo (crítico para fingerprinting)
   - **fr** — Facebook request token
   - **sb** — Secure browsing token

### Método 2: Chrome DevTools

1. Abrí Facebook en Chrome (ya logueado)
2. Presioná **F12** para abrir DevTools
3. Ve a la pestaña **Application** → **Cookies** → **https://www.facebook.com**
4. Buscá y copiá los valores de las cookies mencionadas arriba

## Paso 2: Configurar en EasyPanel

En EasyPanel, abrí tu proyecto **fb-scraper** → **Environment**:

```bash
FB_COOKIE_C_USER=100006593702977
FB_COOKIE_XS=33%3A6NdpMUtKxa1HCg%3A2%3A1770238487%3A-1%3A-1%3A%3AAcyZ87RZa5LloAr_lyhJWkpp0lmmF7lV9S1HaLKmTgBU
FB_COOKIE_DATR=5bGDabP7hjHkcgpOcZNmscZs
FB_COOKIE_FR=2REgJSFJM6fzZbClW.AWdx9s8I5IUgX6yI4F39ryjMU0vs9KZsOeoKKXX9tCZSOiKvLD8.Bpkf-3..AAA.0.0.BpkgZL.AWca7SVnvac0gWXyVKRWiHarYWo
FB_COOKIE_SB=5bGDaVcc0Te_Icgrp0SyJ92a
```

**Guardá** y **redesplegá** el servicio (EasyPanel debería rebuildearse automáticamente).

## Paso 3: Verificar

En los logs de EasyPanel deberías ver:

```
Facebook cookies found, injecting into browser context...
Injected 5 Facebook cookies successfully.
```

## ⚠️ Seguridad

- **NO las compartas** con nadie (son como tu contraseña)
- Si cambiás tu contraseña de Facebook, las cookies se invalidan — necesitás obtener nuevas
- Las cookies expiran después de 30-60 días generalmente
- **NO las commitees** al repositorio Git — solo como env vars

## Datos Disponibles

### Con Proxy + Cookies ✅

- Autor
- Caption completo
- Reacciones
- Shares
- Imagen/thumbnail
- URL canónica
- _Potencialmente_ comentarios y vistas (si Facebook no pide checkpoint)

### Sin Cookies (Solo Proxy) ⚠️

- Autor
- Caption completo
- Reacciones
- Shares
- Imagen/thumbnail
- URL canónica
- ❌ Sin comentarios ni vistas

## Troubleshooting

**"Facebook redirected to security checkpoint"**

- Facebook detectó login sospechoso
- Puede pasar si usás las mismas cookies desde múltiples IPs
- Solución: Obtené nuevas cookies o usá sin cookies

**"Facebook redirected to login page"**

- Cookies expiradas o inválidas
- Solución: Obtené nuevas cookies de tu sesión actual

**"Injected 0 cookies"**

- Variables de entorno no configuradas correctamente
- Verifica los nombres: `FB_COOKIE_C_USER`, `FB_COOKIE_XS`, etc.

## Estado Actual (Febrero 2026)

Actualmente el scraper funciona **sin cookies** extrayendo datos públicos de OpenGraph meta tags. Las cookies están implementadas pero pueden triggear checkpoints de seguridad de Facebook, así que se recomienda:

1. **Usar solo proxy** (sin cookies) para datos públicos confiables
2. **Proxy + cookies** solo si necesitás comentarios/vistas y estás dispuesto a renovar cookies frecuentemente
