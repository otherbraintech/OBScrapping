# Configuración de Cookies de Facebook

Para obtener datos completos de engagement (comentarios, visualizaciones), el scraper necesita acceder a Facebook como usuario logueado.

## Paso 1: Obtener tus Cookies de Facebook

1. **Abrí Facebook** en Chrome (ya logueado)
2. Presioná **F12** para abrir DevTools
3. Ve a la pestaña **Application** (o **Aplicación** si está en español)
4. En el menú lateral izquierdo, expandí **Cookies** → **https://www.facebook.com**
5. Buscá y copiá los valores de estas dos cookies:
   - **c_user** — Tu user ID numérico de Facebook
   - **xs** — Token de sesión (es un string largo con caracteres especiales)

## Paso 2: Configurar en EasyPanel

1. En EasyPanel, abrí tu proyecto **fb-scraper**
2. Ve a la sección **Environment** (Variables de entorno)
3. Agregá estas dos variables:

   ```
   FB_COOKIE_C_USER=<pega aquí el valor de c_user>
   FB_COOKIE_XS=<pega aquí el valor de xs>
   ```

4. **Guardá** y **redesplegá** el servicio (EasyPanel debería reconstruir automáticamente)

## Paso 3: Probar

Ejecutá un nuevo scrape desde n8n. En los logs de EasyPanel deberías ver:

```
Facebook cookies found, injecting into browser context...
Cookies injected successfully.
```

Y el resultado ahora debería incluir:

- ✅ `comments`: "16"
- ✅ `views`: "5,5 mil visualizaciones"

## ⚠️ Importante — Seguridad

- **No compartas estas cookies** con nadie (son como tu contraseña)
- Si cambiás tu contraseña de Facebook, tenés que obtener nuevas cookies
- Las cookies expiran después de 30-60 días generalmente — si el scraper deja de funcionar, actualizá las cookies

## Opcional: Scraping sin Cookies

Si no configurás las cookies, el scraper funciona igual pero con datos limitados:

- ✅ Autor, caption, reacciones (del OG title), shares, imagen, thumbnail
- ❌ No: comentarios, visualizaciones
