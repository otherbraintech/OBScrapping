# Actualización de Arquitectura DB: Scraping Masivo (Páginas/Perfiles)

Para implementar el scraping masivo de perfiles/páginas de Facebook y permitir que el sistema guarde múltiples publicaciones por cada ejecución, se requiere actualizar el esquema de base de datos (Prisma) y el backend.

## 1. Cambios Sugeridos en `schema.prisma`

Actualmente la tabla `Result` guarda métricas globales por cada "ScrapeRequest". Para soportar múltiples publicaciones, se recomienda crear una nueva tabla `PostResult`.

```prisma
model ScrapeResult {
  id           String   @id @default(uuid())
  content_type String   // "reel", "post" o "page_feed"
  reactions    Int?     @default(0)
  comments     Int?     @default(0)
  shares       Int?     @default(0)
  views        Int?     @default(0)
  scraped_at   DateTime @default(now())
  raw_data     Json?    // Aquí se guardará el JSON completo del scraper

  // Relaciones
  request_id   String
  request      ScrapeRequest @relation(fields: [request_id], references: [id])

  // Nueva relación para múltiples posts (cuando content_type == "page_feed")
  posts        PostResult[]
}

model PostResult {
  id             String   @id @default(uuid())
  post_id        String?  // ID interno de FB
  url            String?  // URL directa de la publicación (/reel/ID/ o /posts/ID/)
  thumbnail      String?
  caption        String?  @db.Text

  // Métricas específicas de cada post
  reactions      Int      @default(0)
  comments       Int      @default(0)
  shares         Int      @default(0)
  views          Int      @default(0)

  // Metadatos
  scraped_at     DateTime @default(now())

  // Relación con el resultado padre
  result_id      String
  result         ScrapeResult @relation(fields: [result_id], references: [id])
}
```

## 2. Lógica del Scraper (Backend)

Cuando el scraper detecta una URL de **perfil o página** (ej: `facebook.com/usuario`), se ejecutará el `FacebookPageScraper`.

- Este scraper realizará scroll (por defecto 5 veces, ajustable).
- Extraerá una lista de objetos en `data.posts`.
- Cada objeto contendrá: `url`, `id`, `thumbnail`, y los conteos de `reactions_count`, `comments_count`, `shares_count`, `views_count`.

## 3. Integración con el Frontend

El Frontend deberá:

1. **Permitir URLs de perfil**: El backend ya está configurado para enrutar URLs de perfil al scraper masivo.
2. **Visualizar Grilla de Resultados**: Si el `content_type` es `page_feed`, el frontend debe iterar sobre la lista de posts en lugar de mostrar un solo bloque de métricas.
3. **Botón de Recarga**: Al hacer click en una publicación de la grilla, el frontend podría disparar un scrape individual si se requiere máxima precisión (aunque el scraping masivo ya trae métricas aproximadas).

## 4. Próximos pasos en el Backend

- Se ha actualizado el `FacebookPageScraper` para ser más agresivo capturando visualizaciones en la vista de perfil.
- Se ha corregido la detección de URLs compartidas para que no se confundan con perfiles.

---

_Nota: Este archivo sirve como guía para la actualización de las tablas Prisma mencionada por el usuario._
