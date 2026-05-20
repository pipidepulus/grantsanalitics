# Comandos para ejecutar Pipidepulus AI

Ejecutar en orden, cada comando en una terminal separada donde se indique.

---

## 1. Iniciar PostgreSQL

```bash
sudo service postgresql start
```

Verificar que está corriendo:

```bash
sudo service postgresql status
pg_isready
```

---

## 2. Ejecutar migraciones de base de datos (solo si hay cambios pendientes)

```bash
cd /home/daniel/grantsanalitics/backend
source .venv/bin/activate
alembic upgrade head
```

---

## 3. Iniciar el Backend (Terminal 1 — dejar abierta)

```bash
cd /home/daniel/grantsanalitics/backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verificar que funciona:

```bash
curl http://localhost:8000/api/health
```

Debe responder: `{"status":"healthy","app":"Pipidepulus AI"}`

---

## 4. Iniciar el Frontend (Terminal 2 — dejar abierta)

```bash
cd /home/daniel/grantsanalitics/frontend
npm run dev
```

---

## 5. Abrir la aplicación

Abrir en el navegador:

```
http://localhost:3000
```

---

## Detener todo (en orden inverso)

```bash
# Terminal 2: Ctrl+C (detiene frontend)
# Terminal 1: Ctrl+C (detiene backend)
# Luego:
sudo service postgresql stop
```
