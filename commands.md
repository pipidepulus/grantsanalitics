# Commands — Pipidepulus AI

## 1. PostgreSQL (pgvector)

```bash
# Verificar si el contenedor está corriendo
docker ps | grep pipidepulus_db

# Si no está corriendo, arrancarlo
docker start pipidepulus_db

# Si no existe el contenedor (primera vez o fue eliminado)
docker run -d \
  --name pipidepulus_db \
  -e POSTGRES_USER=pipidepulus \
  -e POSTGRES_PASSWORD=pipidepulus \
  -e POSTGRES_DB=pipidepulus_db \
  -p 5433:5432 \
  pgvector/pgvector:pg16
```

## 2. Backend (FastAPI)

```bash
# Activar el entorno virtual
source /home/usuario/proyectos/grantsanalitics/.vector_env/bin/activate

# Ir al directorio del backend
cd /home/usuario/proyectos/grantsanalitics/backend

# Arrancar el servidor
DATABASE_URL=postgresql://pipidepulus:pipidepulus@localhost:5433/pipidepulus_db \
OLLAMA_BASE_URL=http://localhost:11434 \
CHROMA_DB_PATH=/home/usuario/proyectos/grantsanalitics/data/vector_db \
STORAGE_LOCAL_PATH=/home/usuario/proyectos/grantsanalitics/data/storage \
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 3. Frontend (Next.js)

```bash
# En otra terminal
cd /home/usuario/proyectos/grantsanalitics/frontend

NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev -- --port 3000
```

## 4. Verificar que todo está ok

```bash
# Health check completo del backend
curl -s http://localhost:8000/api/health | python3 -m json.tool

# Resultado esperado:
# {
#   "status": "healthy",
#   "checks": {
#     "database": { "status": "ok" },
#     "ollama": { "status": "ok" },
#     "ollama_deep": { "status": "ok", ... },
#     "chromadb": { "status": "ok" },
#     "pgvector": { "status": "ok" }
#   }
# }

# Verificar que Ollama tiene los modelos necesarios
ollama list | grep -E "gemma4-pipidepulus|nomic-embed-text"

# Probar el chat
curl -s -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"user_id":"db9c4d62-28f0-496a-afed-983e3ebdce09","message":"hola"}' \
  --max-time 60
```

## URLs

| Servicio | URL |
|----------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| Health check | http://localhost:8000/api/health |
| API docs | http://localhost:8000/docs |

## Notas

- El puerto de PostgreSQL es **5433** (no 5432 — ese lo usa el PostgreSQL del sistema).
- Ollama debe estar corriendo en `localhost:11434` antes de arrancar el backend.
- El `.env` en la raíz del proyecto tiene `OLLAMA_BASE_URL=http://host.docker.internal:11434` que es para Docker — **no usar** si se corre el backend directamente. Pasar las variables de entorno como se muestra arriba.
