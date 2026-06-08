# Phase: Tasks — Migration to Local Ollama + Hybrid Vector Stack

## Change: `ollama-local-migration`
## Goal: Eliminar dependencia OpenAI, migrar a stack local (Ollama + ChromaDB + pgvector)
## Strategy: Single PR (size:exception approved), stacked-to-main

---

## Fase 1 — Configuración y Dependencias

### T1-1: Actualizar `requirements.txt`

**Archivos:** `backend/requirements.txt`

- Remover `openai` (y sus dependencias transitivas que no se usen en otro lado)
- Agregar `chromadb`, `pgvector`, `ollama`
- Mantener `httpx==0.28.0` (ya existe, útil para llamadas a Ollama)

**Verificación:** `pip install -r backend/requirements.txt --dry-run` no debería generar conflictos.

### T1-2: Reescribir `settings` en `config.py`

**Archivos:** `backend/app/config.py`

Reemplazar las clases/vars de OpenAI por las nuevas. La clase `Settings` final debe tener:

```python
class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://pipidepulus:pipidepulus@localhost:5432/pipidepulus_db"

    # Ollama (reemplaza OPENAI_*)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5-coder:14b"
    OLLAMA_MODEL_FALLBACK: str = "phi3"          # Modelo alternativo
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"

    # ChromaDB
    CHROMA_DB_PATH: str = "/vector_db"

    # Feature flag de rollback
    VECTOR_STORE_MODE: str = "hybrid"            # "hybrid" | "openai"

    # App (sin cambios)
    APP_NAME: str = "Pipidepulus AI"
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    CYRANO_THRESHOLD: float = 95.01

    # Storage (sin cambios)
    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_PATH: str = "/var/pipidepulus/storage"
    STORAGE_S3_BUCKET: str = ""
    STORAGE_S3_ENDPOINT_URL: str = ""

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8"}
```

Eliminar completamente las vars `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_VECTOR_STORE_ID`, `OPENAI_PROJECTS_VECTOR_STORE_ID`.

**Verificación:** `Settings()` no debe tener errores de pydantic.

---

## Fase 2 — Migración de Base de Datos

### T2-1: Crear migration Alembic `007`

**Archivos:** `backend/alembic/versions/007_project_embeddings.py`

Generar el archivo de migración con:

```python
"""add document_embeddings table with pgvector
Revision ID: 007
Revises: 006
Create Date: 2026-06-XX
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "007"
down_revision = "006"

def upgrade() -> None:
    # 1. Crear extensión si no existe
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    
    # 2. Crear tabla document_embeddings
    op.create_table(
        "document_embeddings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_doc_id", UUID(as_uuid=True), sa.ForeignKey("uploaded_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float).with_variant(
            sa.dialects.postgresql.VARCHAR(2000), "postgresql")),  # workaround pgvector
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # 3. Índices
    op.execute("CREATE INDEX ON document_embeddings USING GIST (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX ON document_embeddings USING GIN (metadata)")
    op.create_index("idx_doc_emb_project", "document_embeddings", ["project_id"])

    # 4. Columna embedding_id en uploaded_documents
    op.add_column("uploaded_documents", sa.Column("embedding_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_uploaded_doc_embedding",
        "uploaded_documents", "document_embeddings",
        ["embedding_id"], ["id"],
        ondelete="SET NULL"
    )

def downgrade() -> None:
    op.drop_constraint("fk_uploaded_doc_embedding", "uploaded_documents", type_="foreignkey")
    op.drop_column("uploaded_documents", "embedding_id")
    op.drop_index("idx_doc_emb_project", "document_embeddings")
    op.drop_table("document_embeddings")
```

**Verificación:** `alembic upgrade head` debe ejecutar sin errores. `alembic downgrade -1` debe revertir limpiamente.

---

## Fase 3 — Modelos SQLAlchemy

### T3-1: Model `DocumentEmbedding` en `document.py`

**Archivos:** `backend/app/models/document.py`

Agregar después de la clase `UploadedDocument`:

```python
VECTOR_DIM = 768

class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    uploaded_doc_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("uploaded_documents.id"), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(PGVector(VECTOR_DIM))
    metadata: Mapped[dict] = mapped_column(JSON, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Importar PGVector desde pgvector.sqlalchemy en el import de __future__
```
Nota: El import `PGVector` debe venir de `from pgvector.sqlalchemy import Vector as PGVector`.

### T3-2: Exportar `DocumentEmbedding` en `__init__.py`

**Archivos:** `backend/app/models/__init__.py`

```python
from app.models.document import GeneratedDoc, UploadedDocument, DocumentEmbedding
# Actualizar __all__ para incluir "DocumentEmbedding"
```

### T3-3: Relación `embeddings` en `Project`

**Archivos:** `backend/app/models/project.py`

Agregar a `TYPE_CHECKING`:

```python
if TYPE_CHECKING:
    from app.models.document import DocumentEmbedding  # agregar esta línea
```

Agregar a la clase `Project` (después de `uploaded_documents`):

```python
    embeddings: Mapped[list["DocumentEmbedding"]] = relationship(
        back_populates="project", lazy="selectin"
    )
```

Agregar `back_populates="project"` a la relación `embeddings` en el modelo `DocumentEmbedding` (en `document.py`).

**Verificación:** `python -c "from app.models import DocumentEmbedding; from app.models import Project; print(DocumentEmbedding.project, Project.embeddings)"` debe imprimir sin errores.

---

## Fase 4 — Motor Vectorial Híbrido (`vector_store.py`)

### T4-1: Reescribir `vector_store.py` completo

**Archivos:** `backend/app/services/vector_store.py`

El archivo final debe tener la siguiente estructura y contenido:

```python
"""
Hybrid Vector Store service: ChromaDB (static KB) + pgvector (dynamic project docs).
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import chromadb
import ollama
from sqlalchemy import text
from sqlalchemy.orm import Session
from pgvector.sqlalchemy import Vector as PGVector
from app.config import get_settings

if TYPE_CHECKING:
    from app.models.document import DocumentEmbedding

VECTOR_DIM = 768
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Shared: Ollama Embedding Function
# ─────────────────────────────────────────────

class OllamaEmbeddingFn:
    """Custom embedding function wrapping Ollama's /api/embed endpoint."""
    def __init__(self, model: str | None = None):
        self.model = model or get_settings().OLLAMA_EMBEDDING_MODEL

    def embed(self, text: str) -> list[float]:
        resp = ollama.embeddings(model=self.model, prompt=text)
        emb = resp["embedding"]
        # Seguridad: sanitizar NaN / Inf antes de usar
        return [0.0 if (v != v or abs(v) == float('inf')) else v for v in emb]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def safe_vector(vector: list[float]) -> list[float]:
    """Replace NaN and Inf values with 0.0 for pgvector safety."""
    result = []
    for v in vector:
        if (v != v) or (abs(v) == float('inf')):  # NaN check: x != x
            result.append(0.0)
        else:
            result.append(v)
    return result


# ─────────────────────────────────────────────
# ChromaDB Knowledge Base Store
# ─────────────────────────────────────────────

_chroma_client = None
_kb_collection = None


def _ensure_kb():
    global _chroma_client, _kb_collection
    if _chroma_client is None:
        settings = get_settings()
        path = settings.CHROMA_DB_PATH
        _chroma_client = chromadb.PersistentClient(path=path)
        embedding_fn = OllamaEmbeddingFn()
        _kb_collection = _chroma_client.get_or_create_collection(
            name="knowledge_base",
            embedding_function=lambda texts: [
                safe_vector(e) for e in embedding_fn.embed_batch(texts)
            ],
            metadata={"hnsw:space": "cosine"},
        )
    return _kb_collection


def search_knowledge_base(query: str, max_results: int = 10) -> list[dict]:
    """Query ChromaDB knowledge base for static methodology content."""
    col = _ensure_kb()
    if col.count() == 0:
        return []
    kb_emb = OllamaEmbeddingFn().embed(query)
    safe_kb_emb = safe_vector(kb_emb)
    results = col.query(
        query_texts=[query],
        n_results=max_results,
        include=["documents", "metadatas", "distances"],
    )
    items = []
    for i in range(len(results["ids"][0])):
        items.append({
            "content": results["documents"][0][i],
            "score": results["distances"][0][i],
            "filename": (results["metadatas"][0][i] or {}).get("filename", "unknown"),
        })
    return items


def upload_bytes_to_knowledge_base(file_bytes: bytes, filename: str) -> str:
    """Upload document bytes → chunk → embed → ChromaDB. Returns ChromaDB ID."""
    col = _ensure_kb()
    texts = _chunk_document(file_bytes, filename)
    now = datetime.now(timezone.utc)
    ids = [str(uuid.uuid4()) for _ in texts]
    
    # Chunk de metadata
    metadatas = [
        {"filename": filename[:200], "source": "uploaded", "uploaded_at": str(now)}
        for _ in texts
    ]
    col.add(
        documents=texts,
        ids=ids,
        metadatas=metadatas,
    )
    return ids[0] if ids else ""


# ─────────────────────────────────────────────
# pgvector Project Documents Store
# ─────────────────────────────────────────────

def search_projects_store(project_id: str | uuid.UUID, query: str, max_results: int = 8) -> list[dict]:
    """Search project documents via pgvector with strict WHERE project_id = $1 filtering."""
    settings = get_settings()
    from app.database import engine, SessionLocal
    
    # Step 1: embed query
    query_vec = safe_vector(OllamaEmbeddingFn().embed(query))
    pid = str(project_id)
    
    # Step 2: execute pgvector query with prepared statement
    with SessionLocal() as db:
        sql = text("""
            SELECT content, metadata, created_at,
                   embedding <=> :query_vec AS distance
            FROM document_embeddings
            WHERE project_id = :project_id
            ORDER BY embedding <=> :query_vec
            LIMIT :max_results
        """)
        result = db.execute(sql, {
            "project_id": pid,
            "query_vec": query_vec,
            "max_results": max_results,
        })
        rows = result.fetchall()
    
    items = []
    for row in rows:
        items.append({
            "content": row[0],
            "metadata": row[1],
            "score": row[2] if row[2] is not None else None,
            "filename": (row[1] or {}).get("filename", "unknown"),
        })
    return items


def upload_bytes_to_projects_store(file_bytes: bytes, filename: str, project_id: str) -> str:
    """Upload document → chunk → embed → INSERT into pgvector with WHERE project_id isolation."""
    from app.database import engine, SessionLocal
    
    texts = _chunk_document(file_bytes, filename)
    embeddings = safe_vector(OllamaEmbeddingFn().embed(texts[0])) if texts else []
    
    # Re-embed all chunks individually
    embeddings_all = [safe_vector(OllamaEmbeddingFn().embed(t)) for t in texts]
    
    now = datetime.now(timezone.utc)
    project_uuid = str(uuid.UUID(project_id))
    
    with SessionLocal() as db:
        # Import model inside for circular import safety
        from app.models.document import DocumentEmbedding
        rows = []
        for i, (text, emb) in enumerate(zip(texts, embeddings_all)):
            rows.append({
                "project_id": project_uuid,
                "chunk_index": i,
                "content": text,
                "embedding": emb,
                "metadata": {
                    "source": "uploaded",
                    "filename": filename[:200],
                    "chunk_index": i,
                    "total_chunks": len(texts),
                    "embedding_model": "nomic-embed-text",
                    "embedding_dim": VECTOR_DIM,
                },
                "created_at": now,
            })
        
        if rows:
            db.bulk_insert_mappings(DocumentEmbedding, rows)
            db.commit()
    
    # Update uploaded_documents.indexing_status for all files of this project
    # (simplified: mark all existing pending as indexed after upload)
    with SessionLocal() as db:
        from app.models.document import UploadedDocument
        uploaders = (
            db.query(UploadedDocument)
            .filter(UploadedDocument.project_id == project_uuid, UploadedDocument.indexing_status == "pending")
            .all()
        )
        for ud in uploaders:
            ud.indexing_status = "indexed"
        if uploaders:
            db.commit()
    
    return project_uuid  # Return project_id as the storage identifier


# ─────────────────────────────────────────────
# Chunking (shared between ChromaDB and pgvector)
# ─────────────────────────────────────────────

def _chunk_document(file_bytes: bytes, filename: str) -> list[str]:
    """Split document into chunks. Simple text split — extend for PDF/DOCX later."""
    # TODO: Implement proper PDF extraction with pdfplumber
    # TODO: Implement DOCX extraction with python-docx
    # For now: treat as UTF-8 text and chunk by ~800 chars with 200 overlap
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1", errors="replace")
    
    if len(text) <= 800:
        return [text]
    
    chunks = []
    chunk_size = 800
    overlap = 200
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    
    return chunks
```

**Verificación:** `python -c "from app.services.vector_store import search_knowledge_base, search_projects_store, OllamaEmbeddingFn; print('OK')"` debe imprimir `OK`.

---

## Fase 5 — Capa de Retrieval

### T5-1: Reescribir `retrieval.py`

**Archivos:** `backend/app/services/retrieval.py`

Nuevo contenido:

```python
"""
Retrieval layer — orchestrates ChromaDB (KB) + pgvector (projects) search.
"""

import logging
import uuid
from app.services.vector_store import search_knowledge_base, search_projects_store

logger = logging.getLogger(__name__)


def build_local_search_tools(project_id: uuid.UUID | None) -> list[dict]:
    """Return tool entries for local search: ChromaDB (KB) + pgvector (projects)."""
    tools = []
    
    # ChromaDB KB tool (always available)
    tools.append({
        "type": "function",
        "name": "retrieve_knowledge_base",
        "description": "Busca en la Metodología Propulsa (conocimiento estático).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Consulta a buscar."},
                "max_results": {"type": "integer", "description": "Máximo de resultados.", "default": 10},
            },
            "required": ["query"],
        },
        "strict": True,
    })
    
    # pgvector project tool (only when project context is active)
    if project_id:
        tools.append({
            "type": "function",
            "name": "retrieve_project_documents",
            "description": f"Busca documentos del proyecto {project_id}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Consulta a buscar."},
                    "max_results": {"type": "integer", "description": "Máximo de resultados.", "default": 8},
                },
                "required": ["query"],
            },
            "strict": True,
        })
    
    return tools


def retrieve_project_context(project_id: uuid.UUID, query: str, max_results: int = 8) -> str:
    """Retrieve project documents from pgvector and inject as <project_documents> context."""
    results = search_projects_store(project_id, query, max_results=max_results)
    
    if not results:
        return ""
    
    chunks = []
    for item in results:
        content = item.get("content", "")
        if content.strip():
            # Escapar caracteres HTML para prevenir inyección de contexto malicioso
            content = (content
                        .replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;"))
            chunks.append(f"[Archivo: {item.get('filename', 'unknown')}]\n{content}")
    
    if not chunks:
        return ""
    
    joined = "\n\n---\n\n".join(chunks)
    return f"<project_documents>\n{joined}\n</project_documents>"
```

**Verificación:** `build_local_search_tools(None)` debe retornar 1 tool; `build_local_search_tools(uuid.uuid4())` debe retornar 2 tools.

### T5-2: Actualizar `tools.py` — `handle_search_funding_calls`

**Archivos:** `backend/app/services/tools.py`

Reemplazar función completa:

```python
async def handle_search_funding_calls(args: dict) -> str:
    """Placeholder — web search no disponible en configuración local. TODO: implementar motor de búsqueda local."""
    return json.dumps({
        "status": "not_available",
        "source": "local_placeholder",
        "message": "La búsqueda web requiere configuración cloud. Implementar motor de búsqueda local.",
    })
```

Eliminar `AsyncOpenAI` import de `tools.py`.

### T5-3: Actualizar `tools.py` — `handle_extract_requirements`

**Archivos:** `backend/app/services/tools.py`

Reemplazar `AsyncOpenAI` por `httpx.AsyncClient` llamado a Ollama:

```python
async def handle_extract_requirements(args: dict) -> str:
    _settings = get_settings()
    prompt = f"{EXTRACT_REQUIREMENTS_PROMPT}\n\n<document>\n{args['document_text']}\n</document>"
    
    url = _settings.OLLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": _settings.OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
    }
    
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    
    # Parse JSON from text (same as before, extracting ```json ... ```)
    extracted = {}
    try:
        json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if json_match:
            extracted = json.loads(json_match.group(1))
        else:
            extracted = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        extracted = {"raw_extraction": text}
    
    # Save to db (same logic as before)
    def _save_to_db() -> str:
        db = SessionLocal()
        try:
            # ... same save logic as current handle_extract_requirements ...
            # [keep exact existing save logic unchanged]
            ...
        finally:
            db.close()

    saved_id = await asyncio.to_thread(_save_to_db)
    
    return json.dumps({
        "status": "success",
        "call_spec_id": saved_id,
        "document_length": len(args["document_text"]),
        "extracted": extracted,
        "message": "Requisitos extraídos y guardados correctamente.",
    })
```

### T5-4: Actualizar `tools.py` — `handle_save_to_project_memory`

**Archivos:** `backend/app/services/tools.py`

Reemplazar método completo:

```python
def handle_save_to_project_memory(args: dict, db: Session) -> str:
    project_id = args["project_id"]
    summary = args["summary"]
    
    project = db.query(Project).filter(Project.id == uuid.UUID(project_id)).first()
    if not project:
        return json.dumps({"status": "error", "message": "Proyecto no encontrado"})
    
    # Usar el nuevo vector store (pgvector)
    filename = f"proyecto_{project.title.replace(' ', '_')[:50]}.md"
    storage_id = upload_bytes_to_projects_store(
        file_bytes=summary.encode("utf-8"),
        filename=filename,
        project_id=project_id,
    )
    
    project.status = ProjectStatus.completed
    db.commit()
    
    return json.dumps({
        "status": "success",
        "message": f"Proyecto '{project.title}' guardado en memoria de proyectos.",
        "storage_id": storage_id,
    })
```

**Verificación:** Las funciones modificadas de `tools.py` deben importarse sin errores. `handle_search_funding_calls` debe retornar placeholder.

---

## Fase 6 — Motor de Agente (`ai_agent.py`)

### T6-1: Reescribir `ai_agent.py` con Ollama (batch mode)

**Archivos:** `backend/app/services/ai_agent.py`

Cambios masivos:

1. **Eliminar** `from openai import AsyncOpenAI` y `client = AsyncOpenAI(api_key=...)`
2. **Agregar** imports: `httpx`, `json`, `time`, `logger`, `get_settings`, `OllamaEmbeddingFn`
3. **Agregar función `_get_ollama_url()`:**

```python
def _get_ollama_url():
    settings = get_settings()
    base = settings.OLLAMA_BASE_URL.rstrip("/")
    return f"{base}/v1/chat/completions"

async def _ollama_chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """Call Ollama /v1/chat/completions. Returns parsed JSON response."""
    settings = get_settings()
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": 0.7,
    }
    if tools:
        payload["tools"] = tools
    
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(_get_ollama_url(), json=payload)
        resp.raise_for_status()
        return resp.json()
```

4. **Agregar `_parse_ollama_response()`:**

```python
def _parse_ollama_response(response_json: dict) -> tuple[str, list[dict] | None]:
    choices = response_json.get("choices", [])
    if not choices:
        return "No se recibió respuesta del modelo.", None
    
    message = choices[0].get("message", {})
    content = message.get("content", "")
    
    tool_calls = None
    if message.get("tool_calls"):
        tool_calls = []
        for tc in message["tool_calls"]:
            func = tc["function"]
            tool_calls.append({
                "name": func["name"],
                "arguments": json.loads(func.get("arguments", "{}")),
            })
    
    return content, tool_calls
```

5. **Módulo `_ensure_model_available()`:** (auto fallback)

```python
async def _ensure_model_available() -> str:
    """Auto-detect available model; fallback to OLLAMA_MODEL_FALLBACK."""
    settings = get_settings()
    
    # Check current model
    try:
        async with httpx.AsyncClient() as client:
            tags_resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            models = [m["name"] for m in tags_resp.json().get("models", [])]
            if settings.OLLAMA_MODEL in models:
                return settings.OLLAMA_MODEL
    except Exception:
        pass
    
    # Try fallback
    if settings.OLLAMA_MODEL_FALLBACK:
        try:
            async with httpx.AsyncClient() as client:
                fback = settings.OLLAMA_MODEL_FALLBACK
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/generate",
                    json={"model": fback, "prompt": "test", "stream": False},
                )
                if resp.status_code == 200:
                    logger.info("ollama_model_fallback_activated", extra={"model": fback})
                    return fback
        except Exception:
            pass
    
    raise RuntimeError(
        f"Modelo no encontrado. Ejecuta: ollama pull {settings.OLLAMA_MODEL}"
    )
```

6. **Actualizar `_build_tools()`:**

```python
def _build_tools(project_id: uuid.UUID | None) -> list[dict]:
    from app.services.retrieval import build_local_search_tools
    from app.services.tools import TOOL_DEFINITIONS
    
    tools = list(TOOL_DEFINITIONS)
    tools.extend(build_local_search_tools(project_id))
    # web_search_preview eliminado — no disponible localmente
    return tools
```

7. **Actualizar `_process_response()`**:

El loop iterativo se mantiene (tool-call → execute → response → tool-call). Pero cambia:

- `client.responses.create(model=...)` → `await _ollama_chat(messages, tools)`
- `response.output_item.added` (OpenAI) → `response.choices[0].message.tool_calls` (Ollama)
- `response.output[].content[].text` → `response.choices[0].message.content`

8. **Actualizar `process_chat_message()`:**

El wrapper se mantiene igual. Solo cambia la línea:

```python
# BEFORE:
response = await client.responses.create(model=settings.OPENAI_MODEL, ...)

# AFTER:
response = await _ollama_chat(input_messages, tools=tools)
content, tool_calls = _parse_ollama_response(response)
```

### T6-2: Actualizar streaming (`process_chat_message_stream`)

**Archivos:** `backend/app/services/ai_agent.py`

Agregar:

```python
async def _ollama_chat_stream(messages: list[dict], tools: list[dict] | None = None):
    settings = get_settings()
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": messages,
        "tools": tools or [],
        "stream": True,
        "temperature": 0.7,
    }
    
    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream("POST", _get_ollama_url(), json=payload) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        if content := delta.get("content"):
                            yield {"type": "delta", "content": content}
                    except json.JSONDecodeError:
                        pass
```

Actualizar `process_chat_message_stream` para usar `_ollama_chat_stream` en lugar de `client.responses.create(stream=True)`.

**Verificación:** La implementación final de `ai_agent.py` debe:
- No tener imports de `openai`
- Tener `_build_tools(project_id)` que retorna lista de dicts function-calling
- Tener `_process_response(response, ...)` que itera sobre `response.choices[0].message.tool_calls`
- Tener `process_chat_message` y `process_chat_message_stream` con la misma firma pública

---

## Fase 7 — Aplicación (Health Check + Startup)

### T7-1: Actualizar health check en `main.py`

**Archivos:** `backend/app/main.py`

Reemplazar la función `health_check()`:

```python
@app.get("/api/health")
def health_check():
    checks: dict[str, dict] = {}
    all_ok = True
    settings = get_settings()
    
    # --- Database ---
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": str(exc)}
        all_ok = False
        logger.error("health_check: database unreachable", exc_info=exc)
    
    # --- Ollama ---
    checks["ollama"] = {"status": "error", "detail": "not checked"}
    try:
        with httpx.Client(timeout=5) as client:
            r = client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            r.raise_for_status()
            checks["ollama"] = {"status": "ok"}
    except Exception as e:
        checks["ollama"] = {"status": "error", "detail": f"Ollama not reachable: {e}"}
        all_ok = False
    
    # --- ChromaDB ---
    checks["chromadb"] = {"status": "ok"}
    try:
        import chromadb
        ch_client = chromadb.PersistentClient(settings.CHROMA_DB_PATH)
        ch_client.heartbeat()
        checks["chromadb"] = {"status": "ok"}
    except Exception as e:
        checks["chromadb"] = {"status": "error", "detail": str(e)}
        all_ok = False
    
    # --- pgvector ---
    checks["pgvector"] = {"status": "ok"}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT * FROM pg_extension WHERE extname = 'vector'"))
        checks["pgvector"] = {"status": "ok"}
    except Exception as e:
        checks["pgvector"] = {"status": "error", "detail": str(e)}
        all_ok = False
    
    status_code = 200 if all_ok else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if all_ok else "degraded",
            "app": settings.APP_NAME,
            "checks": checks,
        },
    )
```

---

## Fase 8 — Tests

### T8-1: `conftest.py` — Fixtures compartidas para pgvector y ChromaDB

**Archivos:** `backend/tests/conftest.py`

Agregar fixtures:

```python
import pytest
import chromadb
from pgvector.sqlalchemy import Vector as PGVector
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models.document import DocumentEmbedding


@pytest.fixture
def chromadb_test_client():
    """In-memory ChromaDB for testing."""
    client = chromadb.EphemeralClient()
    yield client
    # Ephemeral auto-cleans


@pytest.fixture
def pgvector_test_engine():
    """Ephemeral pgvector table for testing."""
    # TODO: Use sqlite with pgvector dialect or use actual PostgreSQL for tests
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[DocumentEmbedding.__table__])
    Session = sessionmaker(bind=engine)
    yield Session
    Base.metadata.drop_all(engine, tables=[DocumentEmbedding.__table__])
    engine.dispose()
```

### T8-2: `test_agent.py` — Mock Ollama via httpx

**Archivos:** `backend/tests/test_agent.py`

Reemplazar:
- `unittest.mock.patch("openai.AsyncOpenAI")` → `unittest.mock.patch("httpx.AsyncClient")`
- Crear fixture `mock_ollama_response` que retorna JSON compatible con `_parse_ollama_response`

### T8-3: `test_tools.py` — Mock httpx + vector_store

**Archivos:** `backend/tests/test_tools.py`

Reemplazar:
- `unittest.mock.patch("openai.OpenAI")` → `unittest.mock.patch("httpx.AsyncClient")`
- `mock.patch("app.services.vector_store.upload_bytes_to_projects_store")`

### T8-4: `test_integration.py` — pgvector + ChromaDB integration

**Archivos:** `backend/tests/test_integration.py`

Crear tests que usen `chromadb_test_client` + `pgvector_test_engine` fixtures para validar:
- `search_knowledge_base` retorna resultados
- `search_projects_store` filtra por `project_id`
- `upload_bytes_to_projects_store` INSERTa en tabla temporal

### T8-5: `test_vectors.py` — Test de sanitización y chunking

**Archivos:** `backend/tests/test_vectors.py` (nuevo archivo)

Tests unitarios:
- `test_safe_vector`: NaN → 0.0, Inf → 0.0, values válidas no cambian
- `test_chunk_document`: chunks de ~800 chars con 200 overlap

**Verificación final:** `python -m pytest backend/tests/ -v` debe pasar todos los tests.

---

## Resumen de Micro-tareas

| Fase | Tareas | Complejidad |
|------|--------|-------------|
| 1 — Config & Deps | T1-T3 | S |
| 2 — DB Migration | T2-T2 | M |
| 3 — SQLAlchemy Models | T3-T3 | S |
| 4 — Vector Store | T4-T1 | L |
| 5 — Retrieval + Tools | T5-T4 | L |
| 6 — Agent | T6-T2 | L |
| 7 — App/Health | T7-T1 | M |
| 8 — Tests | T8-T5 | L |

**Total: 18 micro-tareas**

---

## Consideraciones de Implementación

1. **Orden de dependency:** Fase 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8
2. **Seguridad crítica:** T4-P4 (sanitización NaN), T5-T2 (prepare statements WHERE project_id = $1), T5-T2 (escaping HTML)
3. **Compatibilidad:** Las firmas públicas de `process_chat_message`, `process_chat_message_stream`, `search_knowledge_base`, `search_projects_store` deben mantenerse compatibles con el frontend
4. **Rollback:** `VECTOR_STORE_MODE` feature flag permite revertir a OpenAI sin code changes
