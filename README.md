# Normalizador COMUNAS_NORM
**Arquitectura y Almacenamiento de Datos — Evaluación 2 · 2026**
Integrantes: Jostin Sáez · Gerardo Millán · Eduardo Díaz

---

## ¿Qué hace esta aplicación?

Normaliza datos de una tabla `COMUNAS_NORM` a partir de un archivo `.txt` con
una comuna por línea. Realiza las siguientes transformaciones:

| Función | Descripción |
|---|---|
| Unificar tipo | Convierte a Título, MAYÚSCULAS o minúsculas |
| Quitar tildes | á→a, é→e, í→i, ó→o, ú→u, ü→u |
| Reemplazar Ñ | ñ→n / Ñ→N |
| Eliminar duplicados | Compara por clave normalizada (detecta variantes) |
| Limpiar espacios | "san  pedro" → "San Pedro" |
| Log de cambios | Registro detallado de cada transformación |
| BD real | Almacena resultado en SQLite (tabla `COMUNAS_NORM`) |

---

## Estructura del proyecto

```
comunas-norm/
├── app.py               # Backend Flask con toda la lógica ETL y API
├── templates/
│   └── index.html       # Interfaz web (drag & drop, opciones, resultados)
├── requirements.txt     # Dependencias Python
├── Procfile             # Comando de inicio para Railway/Heroku
├── railway.json         # Configuración de despliegue Railway
└── README.md            # Este archivo
```

---

## Ejecutar localmente

```bash
# 1. Clonar o descargar el proyecto
cd comunas-norm

# 2. Crear entorno virtual (recomendado)
python -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Iniciar el servidor
python app.py

# 5. Abrir en el navegador
# http://localhost:5000
```

---

## Despliegue en Railway

### Opción A — Desde GitHub (recomendada)
1. Subir este proyecto a un repositorio GitHub
2. Ir a [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub Repo**
3. Seleccionar el repositorio → Railway detecta automáticamente Python
4. El sitio quedará disponible en una URL pública tipo `https://comunas-norm.up.railway.app`

### Opción B — Railway CLI
```bash
# Instalar CLI
npm install -g @railway/cli

# Login
railway login

# Crear proyecto y desplegar
railway init
railway up
```

### Variables de entorno (opcionales)
| Variable | Default | Descripción |
|---|---|---|
| `PORT` | 5000 | Puerto HTTP (Railway lo inyecta automáticamente) |
| `DATABASE_PATH` | `comunas_norm.db` | Ruta del archivo SQLite |

---

## Endpoints de la API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Interfaz web principal |
| POST | `/api/normalizar` | Procesa el archivo y guarda en BD |
| GET | `/api/descargar/<sesion>/<tipo>` | Descarga CSV, log o SQL |
| GET | `/api/comunas` | Lista todas las comunas en BD (JSON) |
| POST | `/api/limpiar` | Vacía la base de datos |

---

## Base de datos SQLite

```sql
-- Tabla de comunas normalizadas
CREATE TABLE COMUNAS_NORM (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_comuna  TEXT NOT NULL UNIQUE,
    fecha_insercion TEXT NOT NULL
);

-- Log detallado de cada procesamiento
CREATE TABLE PROCESO_LOG (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_id  TEXT NOT NULL,
    linea_num  INTEGER,
    valor_orig TEXT,
    valor_norm TEXT,
    estado     TEXT,   -- OK | MODIFICADO | DUPLICADO
    fecha      TEXT NOT NULL
);
```
