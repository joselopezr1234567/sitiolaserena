# sitiolaserena

## Deploy en Render (Backend + PostgreSQL)

### 1) Preparar variables

Backend lee estas variables:

- `DATABASE_URL` (Render la entrega desde la base)
- `FRONTEND_URL` (URL donde estará el sitio estático)
- `CORS_ORIGIN` (normalmente igual a `FRONTEND_URL`)
- `TRANSBANK_ENV` (`INTEGRATION` o `PRODUCTION`)
- `TRANSBANK_COMMERCE_CODE` y `TRANSBANK_API_KEY` (solo si `PRODUCTION`)

Ejemplo local: [backend/.env.example](file:///Applications/proyectos/sitiolaserena/backend/.env.example)

### 2) Crear servicios en Render

Opción recomendada: usar el Blueprint.

- En Render: New + Blueprint
- Conectar tu repo `joselopezr1234567/sitiolaserena`
- Render detecta `render.yaml` y crea:
  - Postgres: `sitiolaserena-db`
  - Web service: `sitiolaserena-backend`

Archivo: [render.yaml](file:///Applications/proyectos/sitiolaserena/render.yaml)

### 3) Cargar tu base de datos (productos, pedidos, etc.)

Render crea una base vacía. Para subir tus tablas y datos desde tu computador:

1. Exporta tu base local:
   ```bash
   pg_dump -U macbook -d pizzeria_db -Fc -f backup.dump
   ```
   Si en `pg_restore` te aparece algo como `unrecognized configuration parameter "transaction_timeout"`, es porque tu `pg_dump` es de una versión más nueva que el Postgres de Render. Solución recomendada: usa `pg_dump`/`pg_restore` versión 16 para generar el dump.
2. En Render, copia el “External Database URL” de tu Postgres.
3. Importa:
   ```bash
   pg_restore --no-owner --no-privileges -d "POSTGRES_URL_DE_RENDER" backup.dump
   ```

### 4) Frontend

El frontend es estático. Cuando lo subas a hosting (Render Static Site / Netlify / Vercel):

- Cambia la URL del backend en: [frontend/config.js](file:///Applications/proyectos/sitiolaserena/frontend/config.js)
  - `API_BASE_URL: 'https://TU_BACKEND_RENDER.onrender.com'`

### 5) Dominio (NIC Chile)

- Apunta el dominio del frontend al proveedor donde alojes el sitio estático.
- En Render (backend) puedes agregar un “Custom Domain” para la API si quieres algo tipo `api.tudominio.cl`.
- Asegura que `FRONTEND_URL` y `CORS_ORIGIN` en Render coincidan con tu dominio real del frontend.
