# Guía de Configuración de Proxy

Este proyecto utiliza proxies residenciales de **DataImpulse** para bypasear la detección de Cloudflare y sistemas anti-bot de Facebook.

## Variables de Entorno Requeridas

Configurá estas variables en EasyPanel (Environment):

```bash
PROXY_HOST=gw.dataimpulse.com
PROXY_PORT=823
PROXY_USERNAME=6c675aa9e647f1e97050
PROXY_PASSWORD=45d8be60aec72774
```

## ⚠️ Importante - Seguridad

- **NUNCA** commitees estas credenciales al repositorio Git
- Solo configuralas como variables de entorno en EasyPanel
- Son credenciales privadas de tu cuenta de DataImpulse

## Cómo Funciona

1. El scraper lee las credenciales del proxy desde las env vars
2. Playwright configura el browser context para rutear todo el tráfico por el proxy
3. Las requests ahora parecen venir de una **IP residencial** (no datacenter)
4. Cloudflare ve tráfico "normal" y permite el acceso
5. Se puede acceder al contenido completo de Facebook

## Verificación

En los logs de EasyPanel deberías ver:

```
Using proxy: gw.dataimpulse.com:823
```

Si ves este mensaje, el proxy está configurado y funcionando correctamente.

## Notas Técnicas

- **Tipo de proxy**: HTTP/HTTPS proxy con autenticación
- **Protocolo**: HTTP (Playwright se encarga de HTTPS)
- **Rotación de IPs**: DataImpulse rota automáticamente las IPs
- **Geolocalización**: Las IPs son de la región configurada en tu cuenta

## Troubleshooting

**"No proxy configured - may be blocked by Cloudflare"**

- Variables de entorno no configuradas en EasyPanel
- Verifica que los nombres sean exactos: `PROXY_HOST`, `PROXY_PORT`, etc.

**"Proxy connection failed"**

- Credenciales incorrectas
- Cuenta de DataImpulse suspendida o sin crédito
- Verifica que las credenciales estén actualizadas
