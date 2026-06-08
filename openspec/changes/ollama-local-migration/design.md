# Diseño Técnico — Migración Ollama Local + Stack Vectorial Híbrido

> **Change:** `ollama-local-migration`
> **Estado:** Draft
> **Depende de:** `proposal.md`, `specs/vector-engine/spec.md`, `specs/vector-hybrid/spec.md`, `specs/retrieval-isolation/spec.md`, `specs/text-generation/spec.md`

---

## 1. Contexto y Motivación

### 1.1 Situación actual

El backend actual (`pipidepulus`) depende de tres servicios externos de OpenAI:

| Servicio | Ubicación actual | Propósito |
|---|---|---|
| **OpenAI API** | `OPENAI_API_KEY` + `AsyncOpenAI` | Modelado de texto (`gpt-5-mini`) |
| **OpenAI Embeddings** | `text-embedding-3-small` | Generación de embeddings |
| **OpenAI Vector Store API** | `OPENAI_VECTOR_STORE_ID` + `OPENAI_PROJECTS_VECTOR_STORE_ID` | Búsqueda semántica (KB estática + documentos de proyectos) |

Código afectado distribuido en 4 archivos:

- `app/services/ai_agent.py` — `AsyncOpenAI().responses.create()` para generación + tool-calling
- `app/services/vector_store.py` — `client.vector_stores` y `client.files` para embeddings/uploads
- `app/services/retrieval.py` — `client.vector_stores.search()` para recuperación filtrada
- `app/services/tools.py` — `AsyncOpenAI` en `handle_extract_requirements` y `handle_save_to_project_memory`

Problemas: costos API, latencia impredecible, dependencia de conectividad exterior, imposibilidad de operar en ambientes offline.

### 1.2 Objetivo

Reemplazar toda dependecia de OpenAI por un stack local:

- **Ollama** (`http://localhost:11434`) con `qwen2.5-coder:14b-16k` → generación de texto
- **Ollama** con `nomic-embed-text` → embeddings
- **ChromaDB** local → knowledge base estática
- **PostgreSQL + pgvector** → documentos de proyecto con aislamiento por `project_id`

Resultado: herramienta 100% privada, sin keys, funcinando en local o cualquier servidor, con cero contaminación cruzada entre proyectos.

---

## 2. Arquitectura General

```
┌──────────────────────────────────────────────────────────────┐
│                     Pipidepulus Backend                      │
│                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐ │
│  │ ai_agent.py  │   │ retrieval.py │   │  tools.py        │ │
│  │ (agente +    │   │ (orquestador │   │  (tools biz      │ │
│  │   loop)      │──▶│  dual-retrie)│   │   logic)         │ │
│  └──────┬───────┘   └──────┬───────┘   └──────────────────┘ │
│         │                  │                                  │
│  ┌──────▼──────────────────▼──────────────────────────────┐  │
│  │              vector_store.py (híbrido)                 │  │
│  │  ┌───────────────────┐  ┌──────────────────────────┐   │  │
│  │  │ ChromaDB Store    │  │  pgvector Store          │   │  │
│  │  │ knowledge_base    │  │  document_embeddings     │   │  │
│  │  └───────────────────┘  └──────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────┬─────────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   ┌───────────┐ ┌──────────┐ ┌───────────┐
   │  Ollama   │ │ChromaDB  │ │ PostgreSQL│
   │  API:11434│ │  Local   │ │ + pgvector│
   └───────────┘ └──────────┘ └───────────┘
```

### Principios de diseño

1. **Abstracción del backend vectorial**: las capas superiores (agent, tools) llaman a métodos de `vector_store.py` sin saber qué backend usa internamente.
2. **Aislamiento por `project_id` a nivel SQL**: la cláusula `WHERE project_id = $1` en pgvector garantiza aislamiento, más que el filtrado por atributos de OpenAI.
3. **Sin polling**: pgvector INSERT es síncrono; no se necesita poll de estatus como con OpenAI files.
4. **Compatibilidad de interfaz**: las firmas de métodos públicos se mantienen iguales para que `ai_agent.py` y `retrieval.py` (y por ende `chat.py`) no requieran cambios en las llamadas, solo en la implementación.

---

## 3. Configuración (`app/config.py`)

### 3.1 Vars nuevas

Sustitución de vars de OpenAI por vars locales:

| Variable antigua | → | Nueva variable | Valor default | Descripción |
|---|---|---|---|---|
| `OPENAI_API_KEY` | | `OLLAMA_BASE_URL` | `http://localhost:11434` | Endpoint Ollama |
| `OPENAI_MODEL (gpt-5-mini)` | | `OLLAMA_MODEL` | `qwen2.5-coder:14b` | Modelo de texto |
| _(sin valor)_ | | `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | Modelo embeddings |
| `OPENAI_VECTOR_STORE_ID` | | `CHROMA_KB_PATH` | `/vector_db` | Ruta de persistencia ChromaDB |
| `OPENAI_PROJECTS_VECTOR_STORE_ID` | | `VECTOR_STORE_MODE` | `hybrid` | `hybrid` \| `openai` (feature flag) |
| _(sin valor)_ | | `PGVECTOR_COLLECTION` | _(no aplica)_ | _(no se usa en la migración)_ |

### 3.2 Estructura actualizada de `Settings`

```python
class Settings(BaseSettings):
    # ── DB
    DATABASE_URL: str = "postgresql://pipidepulus:pipidepulus@localhost:5432/pipidepulus_db"

    # ── Ollama (reemplaza OPENAI_*)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5-coder:14b"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"

    # ── ChromaDB
    CHROMA_DB_PATH: str = "/vector_db"

    # ── Feature flag de migración
    VECTOR_STORE_MODE: str = "hybrid"  # "hybrid" | "openai"

    # ── App
    APP_NAME: str = "Pipidepulus AI"
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # ── Cyrano
    CYRANO_THRESHOLD: float = 95.01

    # ── Storage local/S3 (sin cambios)
    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_PATH: str = "/var/pipidepulus/storage"
    STORAGE_S3_BUCKET: str = ""
    STORAGE_S3_ENDPOINT_URL: str = ""

    model_config = {"env_file": "../.env", "env_file_encoding": "utf-8"}
```

### 3.3 `requirements.txt`

```diff
  fastapi==0.115.0
  uvicorn[standard]==0.32.0
  sqlalchemy==2.0.36
  alembic==1.14.0
  psycopg2-binary==2.9.10
  python-dotenv==1.0.1
- openai==1.60.0
+ chromadb==0.5.0
+ pgvector==0.3.0
+ ollama==0.2.1
  python-docx==1.1.2
  python-multipart==0.0.17
  pydantic==2.10.0
  pydantic-settings==2.6.0
  httpx==0.28.0
  prometheus-fastapi-instrumentator==7.0.0
  slowapi==0.1.9
```

---

## 4. Diseño del Motor de Embeddings (`vector_store.py`)

### 4.1 Visión general

Nuevo `vector_store.py` con dos módulos internos y una API externa unificada:

| Método público | Backend | Parámetros clave |
|---|---|---|
| `search_knowledge_base(query, max_results)` | ChromaDB | `query`, `n_results` |
| `search_projects_store(project_id, query, max_results)` | pgvector | `project_id`, `query_vec`, `n_results` |
| `upload_bytes_to_projects_store(bytes, filename, project_id)` | pgvector | bytes, chunking, embed, INSERT |
| `upload_bytes_to_knowledge_base(bytes, filename)` | ChromaDB | bytes, chunking, embed, ChromaDB add |

### 4.2 ChromaDB Knowledge Base Store

```python
import chromadb

# Initialization (solo en startup / primer uso, con lazy loading)
_chroma_client = None
_kb_collection = None

def _ensure_kb():
    global _chroma_client, _kb_collection
    if _chroma_client is None:
        settings = get_settings()
        _chroma_client = chromadb.PersistentClient(settings.CHROMA_DB_PATH)
        _kb_collection = _chroma_client.get_or_create_collection(
            name="knowledge_base",
            embedding_function=chromadb.EmbeddingFunction
            # Se usa un EmbeddingFunction wrapper que llama a Ollama
        )
    return _kb_collection
```

**Embedding function para ChromaDB** (custom embedder que llama a Ollama):

```python
import ollama

class OllamaEmbeddingFn:
    """Custom ChromaDB embedding function that calls Ollama locally."""
    def __init__(self, model: str | None = None):
        self.model = model or get_settings().OLLAMA_EMBEDDING_MODEL
        self.dim = 768  # nomic-embed-text produce 768-dim vectors
    
    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        results = []
        for text in documents:
            resp = ollama.embeddings(model=self.model, prompt=text)
            results.append(resp["embedding"])
        return results
    
    def embed_query(self, query: str) -> list[float]:
        resp = ollama.embeddings(model=self.model, prompt=query)
        return resp["embedding"]
```

**Método `search_knowledge_base()`**:

```python
def search_knowledge_base(query: str, max_results: int = 10) -> list[dict]:
    col = _ensure_kb()
    if not col.count() == 0:
        query_vec = OllamaEmbeddingFn().embed_query(query)
        results = col.query(query_texts=query, n_results=max_results, include=["documents", "metadatas", "distances"])
        items = []
        for i in range(len(results["ids"][0])):
            items.append({
                "content": results["documents"][0][i],
                "score": results["distances"][0][i],
                "filename": (results["metadatas"][0][i] or {}).get("filename", "unknown"),
            })
        return items
    return []
```

Características clave:
- Collection `knowledge_base` se crea automáticamente si no existe.
- Si la collection está vacía, retorna `[]` (no lanza error).
- No hay project_id: es conocimiento estático global.
- Embeddings se generan con `nomic-embed-text` y tienen dimensión 768.

### 4.3 pgvector Project Documents Store

**Tabla `document_embeddings` (migración 007):**

```sql
CREATE TABLE document_embeddings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    uploaded_doc_id UUID REFERENCES uploaded_documents(id) ON DELETE SET NULL,
    chunk_index     INT NOT NULL,
    content         TEXT NOT NULL,
    embedding       VECTOR(768) NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- Índices para rendimiento
    CONSTRAINT document_embeddings_pkey PRIMARY KEY (id)
);

-- Índice pgvector para búsqueda coseno rápida
CREATE INDEX ON document_embeddings USING GIST (embedding vector_cosine_ops);

-- Índice GIN para filtrado por project_id en metadata
CREATE INDEX ON document_embeddings USING GIN (metadata);

-- Índice para ordenar por project_id (WHERE + ORDER BY)
CREATE INDEX ON document_embeddings (project_id, created_at DESC);
```

**Implementación de búsqueda pgvector:**

```python
from sqlalchemy import text
from pgvector.sqlalchemy import Vector

VECTOR_DIM = 768

def _embed_chunks_for_project(texts: list[str], project_id: str) -> list[dict]:
    """Chunks text → embeds each chunk → returns list of SQLAlchemy-serializable dicts."""
    embeddings = OllamaEmbeddingFn().embed_documents(texts)
    rows = []
    for i, (text, emb) in enumerate(zip(texts, embeddings)):
        rows.append({
            "project_id": uuid.UUID(project_id),
            "chunk_index": i,
            "content": text,
            "embedding": emb,  # pgvector driver convierte list[float] → Postgres VECTOR
            "metadata": {
                "source": "chunk",
                "embedding_model": "nomic-embed-text",
            },
            "created_at": datetime.now(timezone.utc),
        })
    return rows

def search_projects_store(project_id: uuid.UUID, query: str, max_results: int = 8) -> list[dict]:
    """Search project document chunks via pgvector cosine similarity with project_id filter."""
    settings = get_settings()
    
    # Step 1: embed the query
    query_vec = OllamaEmbeddingFn().embed_query(query)
    
    # Step 2: execute pgvector query
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
            "project_id": str(project_id),
            "query_vec": query_vec,
            "max_results": max_results,
        })
        rows = result.fetchall()
    
    return [
        {
            "content": row[0],
            "metadata": row[1],
            "score": row[2] if row[2] else None,
            "filename": (row[1] or {}).get("filename", "unknown"),
        }
        for row in rows
    ]
```

**Implementación de `upload_bytes_to_projects_store()` (pgvector): **

```python
def upload_bytes_to_projects_store(file_bytes: bytes, filename: str, project_id: str) -> str:
    """Upload document → chunk → embed per chunk → INSERT every chunk into pgvector.
    
    Returns the project_id string as the storage identifier.
    """
    # Step 1: chunk the document
    # (reutiliza lógica existente de document_splitter/text splitting)
    texts = _chunk_document(file_bytes, filename)  # → list[str]
    
    # Step 2: embed all chunks
    embeddings = OllamaEmbeddingFn().embed_documents(texts)
    
    # Step 3: batch INSERT into document_embeddings
    with SessionLocal() as db:
        rows = []
        now = datetime.now(timezone.utc)
        for i, (text, emb) in enumerate(zip(texts, embeddings)):
            rows.append({
                "project_id": uuid.UUID(project_id),
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
        db.bulk_insert_mappings(DocumentEmbedding, rows)
        db.commit()
    
    # Step 4: update uploaded_documents.embedding_id (FK)
    # Actualiza UploadedDocument.embedding_id = primer chunk id o null
    # Nota: como son múltiples chunks, se usa uploaded_documents.embedding_status = 'indexed'
    
    return str(uuid.UUID(project_id))
```

**Model SQLAlchemy para `DocumentEmbedding`:**

```python
from pgvector.sqlalchemy import Vector as PGVector

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
    
    project: Mapped["Project"] = relationship(back_populates="embeddings")
```

Agregado a `app/models/__init__.py`:

```python
from app.models.document import GeneratedDoc, UploadedDocument, DocumentEmbedding
__all__ = [..., "DocumentEmbedding"]
```

Agregado a `app/models/project.py` (relación):

```python
from app.models.document import DocumentEmbedding

# En clase Project:
embeddings: Mapped[list["DocumentEmbedding"]] = relationship(
    back_populates="project", lazy="selectin"
)
```

---

## 5. Migración Alembic (`007_project_embeddings.py`)

**Archivo nuevo:** `backend/alembic/versions/007_project_embeddings.py`

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
    # 1. Create the extension if not exists
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    
    # 2. Create table
    op.create_table(
        "document_embeddings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_doc_id", UUID(as_uuid=True), sa.ForeignKey("uploaded_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float).with_variant(
            sa.dialects.postgresql.VARCHAR(2000), "postgresql"  # workaround para pgvector
        )),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    # 3. Índice pgvector para búsqueda coseno
    op.execute("CREATE INDEX ON document_embeddings USING GIST (embedding vector_cosine_ops)")
    
    # 4. Índice GIN para filtrado por metadata (project_id etc.)
    op.execute("CREATE INDEX ON document_embeddings USING GIN (metadata)")
    
    # 5. Índice para WHERE project_id filtering
    op.create_index("idx_doc_emb_project", "document_embeddings", ["project_id"])
    
    # 6. Actualizar tabla uploaded_documents con columna embedding_id
    op.add_column("uploaded_documents", sa.Column("embedding_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_uploaded_doc_embedding",
        "uploaded_documents", "document_embeddings",
        ["embedding_id"], ["id"],
        ondelete="SET NULL"
    )
    # Actualizar: los archivos ya indexados → linking
    # (en producción, migrar openai file IDs al nuevo sistema)

def downgrade() -> None:
    op.drop_constraint("fk_uploaded_doc_embedding", "uploaded_documents", type_="foreignkey")
    op.drop_column("uploaded_documents", "embedding_id")
    op.drop_index("idx_doc_emb_project", "document_embeddings")
    op.drop_table("document_embeddings")
```

> **Nota:** La columna `VECTOR(768)` de ChromaDB/pgvector requiere `sqlalchemy-utils` o `pgvector` para el type correct. En la práctica, el alembic usa `ARRAY(Float)` como workaround portable, y deja que pgvector lo reconozca en runtime.

---

## 6. Diseño del Agente (`ai_agent.py`)

### 6.1 Visión general

El agente necesita reemplazar `AsyncOpenAI()` por una llamada HTTP al endpoint Ollama:

```
OLD: client.responses.create(model="gpt-5-mini", input=..., tools=...)
NEW: httpx.post("http://localhost:11434/v1/chat/completions", json={model, messages, tools})
```

### 6.2 Cliente Ollama

```python
import httpx
from app.config import get_settings

OLLAMA_CHAT_URL = None  # cache: http://localhost:11434/v1/chat/completions

def _get_ollama_url():
    global OLLAMA_CHAT_URL
    if OLLAMA_CHAT_URL is None:
        settings = get_settings()
        base = settings.OLLAMA_BASE_URL.rstrip("/")
        OLLAMA_CHAT_URL = f"{base}/v1/chat/completions"
    return OLLAMA_CHAT_URL

async def _ollama_chat(messages: list[dict], tools: list[dict] | None = None, stream: bool = False) -> dict | httpx.Response:
    """Call Ollama /v1/chat/completions endpoint.
    
    Compatible con formato OpenAI: messages con role/content, tools.
    """
    settings = get_settings()
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    payload["temperature"] = 0.7
    
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(_get_ollama_url(), json=payload)
        resp.raise_for_status()
        return resp.json()
```

### 6.3 Adaptación del `process_chat_message()`

**Cambios específicos en `ai_agent.py`:**

1. **Remove:** `from openai import AsyncOpenAI` + `client = AsyncOpenAI(...)`
2. **Add:** `from app.services.vector_store import OllamaEmbeddingFn` (embedding)
3. **Replace** `_build_tools()` → formato de tools para Ollama (function calling en lugar de Responses API):

```python
def _build_tools(project_id: uuid.UUID | None) -> list[dict]:
    """Compose tools for Ollama /v1/chat/completions format.
    
    Replaces OpenAI's Responses API tool format with Ollama-compatible
    function definitions. Same structure as OpenAI's tools format.
    """
    from app.services.tools import TOOL_DEFINITIONS
    from app.services.retrieval import build_local_search_tools
    
    tools = list(TOOL_DEFINITIONS)  # Ya están en formato compatible (function calling)
    tools.extend(build_local_search_tools(project_id))
    
    # Web search ya no está disponible localmente → se comenta
    # tools.append({"type": "web_search_preview"})
    return tools
```

4. **Replace** `client.responses.create()` → `_ollama_chat()`:

```python
# BEFORE:
response = await client.responses.create(model=settings.OPENAI_MODEL, input=input_messages, tools=tools)

# AFTER:
response = await _ollama_chat(input_messages, tools=tools)
```

5. **Adapt response parsing** (Ollama devuelve formato diferente al de OpenAI Responses):

```python
def _parse_ollama_response(response_json: dict) -> tuple[str, list[dict] | None]:
    """Parse Ollama /v1/chat/completions response for non-streaming.
    
    Returns: (content_text, tool_calls)
    """
    choices = response_json.get("choices", [])
    if not choices:
        return "No se recibió respuesta del modelo.", None
    
    message = choices[0]["message"]
    content = message.get("content", "")
    
    tool_calls = None
    if message.get("tool_calls"):
        tool_calls = []
        for tc in message["tool_calls"]:
            func = tc["function"]
            tool_calls.append({
                "name": func["name"],
                "arguments": json.loads(func["arguments"]),
            })
    
    return content, tool_calls
```

6. **Stream adaptation** → `process_chat_message_stream()`:

```python
async def _ollama_chat_stream(messages: list[dict], tools: list[dict] | None = None):
    """Stream response from Ollama, yielding SSE-like dicts."""
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
                        if delta := data.get("choices", [{}])[0].get("delta", {}):
                            if text := delta.get("content"):
                                yield {"type": "delta", "content": text}
                    except json.JSONDecodeError:
                        pass
```

### 6.4 Tool-calling loop

La estructura del loop iterativo se mantiene (tool-call → execute → response → tool-call → …), con cambio clave: el loop debe ahora:

1. Recibir response del modelo.
2. Verificar si tiene `tool_calls`.
3. Si no → retornar contenido final.
4. Si sí → ejecutar herramientas, construir `tool_results`, y llamar de nuevo.

---

## 7. Layer de Retrieval (`retrieval.py`)

### 7.1 `build_local_search_tools()`

```python
def build_local_search_tools(project_id: uuid.UUID | None) -> list[dict]:
    """Return tool entries for local search: ChromaDB (KB) + pgvector (projects).
    
    When project_id is active, both stores are included.
    When no project is active, only KB is used (global methodology).
    """
    from app.services.vector_store import search_knowledge_base, search_projects_store
    
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
    
    # pgvector project tool (only when project is active)
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
```

### 7.2 `retrieve_project_context()`

```python
def retrieve_project_context(project_id: uuid.UUID, query: str, max_results: int = 8) -> str:
    """Retrieve project documents from pgvector and inject as <project_documents> context."""
    results = search_projects_store(project_id, query, max_results=max_results)
    
    if not results:
        return ""
    
    chunks = []
    for item in results:
        content = item.get("content", "")
        if content.strip():
            chunks.append(f"[Archivo: {item.get('filename', 'unknown')}]\n{content}")
    
    if not chunks:
        return ""
    
    joined = "\n\n---\n\n".join(chunks)
    return f"<project_documents>\n{joined}\n</project_documents>"
```

---

## 8. Tools (`tools.py`)

### 8.1 Herramientas que NO cambian

| Tool | ¿Cambia? | Motivo |
|---|---|---|
| `handle_calculate_budget` | ❌ | Lógica pura, sin OpenAI |
| `handle_generate_word_document` | ❌ | Usa python-docx, sin OpenAI |
| `handle_run_diagnostic` | ❌ | Preparación de datos, evaluacion por LLM |
| `handle_save_project_data` | ❌ | CRUD de SQLAlchemy puro |
| `handle_save_diagnostic_result` | ❌ | CRUD de SQLAlchemy puro |

### 8.2 Herramientas que SÍ cambian

**`handle_extract_requirements()`:**

```diff
  from openai import AsyncOpenAI
- _client = AsyncOpenAI(api_key=_settings.OPENAI_API_KEY)
+ _client = httpx.AsyncClient()
  
- response = await _client.responses.create(model=_settings.OPENAI_MODEL, input=prompt)
+ resp = await _client.post(ollama_url, json={"model": _settings.OLLAMA_MODEL, "messages": [{"role":"user","content":prompt}]})
+ text = resp.json()["choices"][0]["message"]["content"]
```

**`handle_save_to_project_memory()`:**

Reemplaza `client.files.create()` + `client.vector_stores.files.create()` por pgvector INSERT:

```python
from app.services.vector_store import upload_bytes_to_projects_store

def handle_save_to_project_memory(args: dict, db: Session) -> str:
    # ... (mismo project lookup)
    
    summary = args["summary"]
    
    # Usar el nuevo vector store (pgvector) en lugar de OpenAI
    project_id_str = str(project_id)
    storage_id = upload_bytes_to_projects_store(
        file_bytes=summary.encode('utf-8'),
        filename=f"proyecto_{project.title.replace(' ', '_')[:50]}.md",
        project_id=project_id_str,
    )
    
    project.status = ProjectStatus.completed
    db.commit()
    
    return json.dumps({
        "status": "success",
        "message": f"Proyecto '{project.title}' guardado en memoria de proyectos.",
        "storage_id": storage_id,
    })
```

**`handle_search_funding_calls()`:**

Se convierte en un placeholder (ya que web search no tiene equivalente local directo):

```python
async def handle_search_funding_calls(args: dict) -> str:
    """Placeholder — web search no disponible en configuración local.
    
    TODO: implementar búsqueda local o integrar un motor de búsqueda alternativo.
    """
    return json.dumps({
        "status": "not_available",
        "source": "local_placeholder",
        "message": "La búsqueda web requiere configuración cloud. Implementar motor de búsqueda local."
    })
```

---

## 9. Health Check (`main.py`)

```diff
 @app.get("/api/health")
 def health_check():
     checks: dict[str, dict] = {}
     all_ok = True
     
     # --- Database (sin cambios) ---
     ...
     
-    # --- OpenAI key configured ---
-    if settings.OPENAI_API_KEY:
-        checks["openai"] = {"status": "ok"}
-    else:
-        checks["openai"] = {"status": "error", "detail": "OPENAI_API_KEY not configured"}
-
-    # --- Vector stores configured ---
-    vs_missing = [...]
+    # --- Ollama health ---
+    checks["ollama"] = {"status": "error", "detail": "not checked"}
+    try:
+        with httpx.Client(timeout=5) as client:
+            r = client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
+            r.raise_for_status()
+            checks["ollama"] = {"status": "ok"}
+            all_ok = False
+    except Exception as e:
+        checks["ollama"] = {"status": "error", "detail": f"Ollama not reachable: {e}"}
     
+    # --- ChromaDB health ---
+    checks["chromadb"] = {"status": "ok"}
+    try:
+        import chromadb
+        client = chromadb.PersistentClient(settings.CHROMA_DB_PATH)
+        check = client.heartbeat()
+        checks["chromadb"] = {"status": "ok"}
+    except Exception as e:
+        checks["chromadb"] = {"status": "error", "detail": str(e)}
+        all_ok = False
     
+    # --- pgvector health ---
+    checks["pgvector"] = {"status": "ok"}
+    try:
+        with SessionLocal() as db:
+            db.execute(text("SELECT 1"))
+            # Check pgvector extension
+            ext = db.execute(text("SELECT * FROM pg_extension WHERE extname = 'vector'")).first()
+            if not ext:
+                raise Exception("pgvector extension not found")
+        checks["pgvector"] = {"status": "ok"}
+    except Exception as e:
+        checks["pgvector"] = {"status": "error", "detail": str(e)}
+        all_ok = False
     
     status_code = 200 if all_ok else 503
     return JSONResponse(status_code=status_code, content={
         "status": "healthy" if all_ok else "degraded",
         "app": settings.APP_NAME,
         "checks": checks,
     })
```

---

## 10. Modelo `UploadedDocument` (actualización)

### Columna nueva

Agregar `embedding_id = Column(Uuid, ForeignKey("document_embeddings.id"), nullable=True)` a `UploadedDocument`.

```python
class UploadedDocument(Base):
    # ... columnas existentes ...
    
    # Nueva columna para FK al chunk de document_embeddings (en el futuro)
    embedding_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    
    # Status de indexación (ya existe: indexing_status)
    # Se cambiará a: 'indexed' | 'indexing' | 'failed' | 'pending'
```

### Actualización del modelo de proyecto

Agregar relación `embeddings` en `Project`:

```python
from app.models.document import DocumentEmbedding

# En Project class:
embeddings: Mapped[list["DocumentEmbedding"]] = relationship(
    back_populates="project", lazy="selectin"
)
```

---

## 11. Archivo de Migración (007) — Esquema detallado

### Tabla `document_embeddings`

| Columna | Tipo | Constraints | Descripción |
|---|---|---|---|
| `id` | `UUID` | PK, `gen_random_uuid()` | Chunk identifier |
| `project_id` | `UUID` | FK→`projects.id` CASCADE, NOT NULL, indexed | Aislamiento por proyecto |
| `uploaded_doc_id` | `UUID` | FK→`uploaded_documents.id` SET NULL, nullable | Vinculación con documento original |
| `chunk_index` | `INT` | NOT NULL | Índice dentro del documento |
| `content` | `TEXT` | NOT NULL | Texto del chunk |
| `embedding` | `VECTOR(768)` | NOT NULL | Vector de similitud coseno |
| `metadata` | `JSONB` | NOT NULL, default `'{}'` | filename, source, tags, etc. |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, `now()` | Timestamp de creación |

### Índices

| Índice | Tipo | Columna(s) | Propósito |
|---|---|---|---|
| `idx_doc_emb_embedding` | GiST | `embedding vector_cosine_ops` | Búsqueda coseno rápida |
| `idx_doc_emb_metadata` | GIN | `metadata` | Búsqueda por metadata |
| `idx_doc_emb_project` | B-tree (DEFAULT) | `project_id, created_at DESC` | WHERE project_id filtering |

### `uploaded_documents` — cambios

| Columna | Cambio |
|---|---|
| `vector_store_file_id` | Mantener (backward compat) |
| `embedding_id` _(nuevo)_ | FK → `document_embeddings.id` |
| `indexing_status` | Actualizar valores: `pending` → `indexing` → `indexed` |

---

## 12. Estrategia de Embeddings

### Dimensión y modelo

- **Modelo:** `nomic-embed-text`
- **Dimensión:** 768 (fijo, compatible con pgvector VECTOR(768))
- **Endpoint:** `OLLAMA_BASE_URL/embed` (o `/api/embed` según versión de Ollama)

### Flujo de generación

```
documento_bytes ──▶ chunker ──▶ [chunk_1, chunk_2, ..., chunk_N]
                                                      │
                                         cada chunk ──▶ ollama/embed/nomic-embed-text
                                                      │
                                                  [emb_1, emb_2, ..., emb_N]
                                                      │
                                          pgvector INSERT batch ──▶ document_embeddings
                                                      │
                                          chromadb add batch ──▶ knowledge_base
```

### Chunking

Reutilizar la lógica actual de `document_generator.py` o crear función `_chunk_document()` en `vector_store.py`:

```python
def _chunk_document(file_bytes: bytes, filename: str) -> list[str]:
    """Split document into chunks suitable for vector indexing."""
    # Si es PDF: usar PyPDF2 o pdfplumber para extraer texto
    # Si es TXT/DOCX: extraer texto directamente
    # Aplicar chunk size ~1000 tokens con overlap ~200
    # Retornar list[str]
    ...
```

---

## 13. Manejo de Errores y Fallbacks

### Escenarios de fallo y mitigación

| Escenario | Error | Mitigación |
|---|---|---|
| Ollama no está corriendo | `ConnectionRefusedError` / HTTP 503 | Health check detecta; mensaje al usuario; feature flag reversion |
| Modelo no disponible en Ollama | `model_not_found` (HTTP 404 de Ollama) | Fallback automático: detectar y probar `OLLAMA_MODEL_FALLBACK`; si falla también, mensaje informativo `ollama pull <modelo>` |
| pgvector extensión no instalada | `pgvector extension not found` | Mensaje: `CREATE EXTENSION IF NOT EXISTS vector;` |
| ChromaDB ruta inválida | `OSError` / `PermissionError` | Crear directorio si no existe; fallback a `/tmp/` |
| Tool-calling falla (qwen2.5-coder) | Formato invalid | Fallback a modo sin herramientas; mensaje al usuario |
| Embedding produce NaN/Inf | ValueError en pgvector | Sanitizar vector (fillna con 0) antes de INSERT |

### Fallback automático de modelo (Auto Model Fallback)

El sistema DEBE detectar automáticamente cuando el modelo configurado en `OLLAMA_MODEL` no está disponible y hacer fallback sin intervención manual.

**Mecanismo:**

1. **Pre-flight check**: Al arranque de la app, listar modelos de Ollama con `GET /api/tags`.
2. **Si el modelo no está listado**:
   - Probar `OLLAMA_MODEL_FALLBACK` (por defecto `"phi3"`)
   - Si el fallback tampoco existe → mensaje informativo: `Modelo no encontrado. Ejecutar: ollama pull <modelo>`
3. **Si Ollama cae runtime** (primer error `ConnectionRefusedError`):
   - En el health check, intentar `ollama pull <modelo>` automáticamente (solo una vez, con retry)
   - Si el pull falla → mantener fallback; si funciona → switchear al modelo original
4. **Si tool-calling falla** (qwen2.5-coder no soporta function calling correctamente):
   - Detectar formato de respuesta incorrecta (sin `tool_calls`)
   - Reintentar con `OLLAMA_MODEL_FALLBACK` que sí soporte tool-calling
   - Si falla el fallback también → deshabilitar herramientas para esta petición; mensaje al usuario
   - El resto de la conversación continúa sin tools

**Config en `config.py`:**

```python
# Modelo principal para generación de texto
OLLAMA_MODEL: str = "qwen2.5-coder:14b"
# Modelo de fallback (probado automáticamente si el principal falla)
OLLAMA_MODEL_FALLBACK: str = "phi3"
# Modelo para embeddings
OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
```

**Implementación en `ai_agent.py`:**

```python
async def _ensure_model_available() -> str:
    """Check if OLLAMA_MODEL is available; try fallback if not. Returns active model name."""
    try:
        async with httpx.AsyncClient() as client:
            tags = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            available = set(tags.json().get("models", []))
            model_names = {m.get("name", "") for m in available}
            if settings.OLLAMA_MODEL in model_names:
                return settings.OLLAMA_MODEL
    except Exception:
        pass  # no verificar, asumir ok
    
    # Intentar fallback
    if settings.OLLAMA_MODEL_FALLBACK:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/generate",
                    json={"model": settings.OLLAMA_MODEL_FALLBACK, "prompt": "test", "stream": False}
                )
                if resp.status_code == 200:
                    return settings.OLLAMA_MODEL_FALLBACK
        except Exception:
            pass
    
    logger.error("ollama_model_not_available",
        extra={"primary": settings.OLLAMA_MODEL, "fallback": settings.OLLAMA_MODEL_FALLBACK})
    raise OllamaModelUnavailable(
        f"No se encontró '{settings.OLLAMA_MODEL}'. "
        f"Ejecuta: ollama pull {settings.OLLAMA_MODEL}"
    )
```

---

### Feature flag `VECTOR_STORE_MODE`

```python
# En config.py
VECTOR_STORE_MODE: str = "hybrid"  # "hybrid" | "openai"

# En vector_store.py
def _is_hybrid() -> bool:
    return get_settings().VECTOR_STORE_MODE == "hybrid"
```

Permite rollback rápido vía `.env` sin code changes.

---

## 14. Estrategia de Testing

### Tests a actualizar

| Test file | ¿Qué cambia |
|---|---|
| `test_agent.py` | Mocke `httpx.AsyncClient` en lugar de `AsyncOpenAI` |
| `test_tools.py` | Mocke `httpx` + `upload_bytes_to_projects_store` |
| `test_integration.py` | Fixture con pgvector (tabla efímera) + ChromaDB in-memory |
| `test_e2e.py` | Mock `ollama` + `chromadb` |

### Nueva fixture para pgvector

```python
@pytest.fixture
def pgvector_test_engine():
    """Create ephemeral pgvector test table."""
    from pgvector.sqlalchemy import Vector
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine("postgresql://test@test:5432/testdb")
    # Crear tabla efímera con pgvector
    Base.metadata.create_all(engine, tables=[DocumentEmbedding.__table__])
    Session = sessionmaker(bind=engine)
    yield Session
    
    # Cleanup
    Base.metadata.drop_all(engine, tables=[DocumentEmbedding.__table__])
    engine.dispose()
```

### Nueva fixture para ChromaDB

```python
@pytest.fixture
def chromadb_test_client():
    """Create in-memory ChromaDB for testing."""
    import chromadb
    client = chromadb.EphemeralClient()
    yield client
    # Cleanup (ephemeral auto-cleans)
```

---

## 15. Plan de Implementación (Fase por Fase)

### Fase 1 — Configuración y dependencias

**Archivos modificados:**

- `backend/app/config.py` — vars nuevas, remoción de `OPENAI_*`
- `backend/requirements.txt` — deps swap
- `backend/.env.example` si existe — actualizar vars

### Fase 2 — Migración de base de datos (007)

**Archivos nuevos:**

- `backend/alembic/versions/007_project_embeddings.py` — tabla + índices

### Fase 3 — Modelos SQLAlchemy actualizados

**Archivos modificados:**

- `backend/app/models/document.py` — agregar `DocumentEmbedding` class
- `backend/app/models/__init__.py` — export `DocumentEmbedding`
- `backend/app/models/project.py` — agregar relación `embeddings`

### Fase 4 — Vector store híbrido

**Archivos modificados:**

- `backend/app/services/vector_store.py` — reescrito completo: ChromaDB + pgvector

### Fase 5 — Retrieval + Tools

**Archivos modificados:**

- `backend/app/services/retrieval.py` — `build_local_search_tools()` + `retrieve_project_context()` con pgvector
- `backend/app/services/tools.py` — `handle_extract_requirements()` adapta a httpx, `handle_save_to_project_memory()` usa pgvector, `handle_search_funding_calls()` placeholder

### Fase 6 — Agente

**Archivos modificados:**

- `backend/app/services/ai_agent.py` — httpx.client(), Ollama response parsing, streaming adaptation

### Fase 7 — Health check y tests

**Archivos modificados:**

- `backend/app/main.py` — health check actualizado
- `backend/tests/*.py` — mocks actualizados

---

## 16. Compatibilidad y Consideraciones

### Formato de herramientas para Ollama

Ollama acepta el formato estándar de OpenAI para tool-calling:

```json
{
  "model": "qwen2.5-coder:14b",
  "messages": [...],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "calculate_budget",
        "description": "...",
        "parameters": {"type": "object", "properties": {...}}
      }
    }
  ]
}
```

Este formato es idéntico al que OpenAI usa internamente para `function_call`. Las `TOOL_DEFINITIONS` de `tools.py` ya están en este formato → no necesitan cambios de estructura.

### Respuesta de Ollama vs OpenAI

| Campo | OpenAI Responses API | Ollama /v1/chat/completions |
|---|---|---|
| Texto final | `response.output[].content[].text` | `response.choices[0].message.content` |
| Tool calls | `response.output[].type == "function_call"` | `response.choices[0].message.tool_calls` |
| Streaming | `response.output_text.delta` | `response.choices[0].delta.content` |
| ID de respuesta | `response.id` | `response.id` |

### pgvector query de similitud coseno

```sql
-- pgvector usa el operador <=> para distancia coseno (menor = más similar)
SELECT content, embedding <=> query_vec
FROM document_embeddings
WHERE project_id = 'p-123'
ORDER BY embedding <=> query_vec
LIMIT 8;
```

Nota: el operador `<=>` en pgvector calcula `1 - cosine_similarity`. Valores más bajos = más similar.

---

## 17. Estrategia de Rollback

### Rollback rápido vía config

Si la migración causa problemas, revertir a OpenAI:

1. `.env`: `VECTOR_STORE_MODE=openai`
2. `config.py`: agregar fallback para `OPENAI_API_KEY`
3. `vector_store.py`: restaurar path `openai` → usar `OpenAI` client

### Rollback de migración DB

```sql
-- Para revertir la migración 007:
DROP TABLE IF EXISTS document_embeddings;
ALTER TABLE uploaded_documents DROP COLUMN IF EXISTS embedding_id;
```

### Modelo alternativo

Si `qwen2.5-coder:14b` no soporta tool-calling correctamente:
1. Revertir a `phi3` o `llama3.1` → solo cambiar `OLLAMA_MODEL` en `.env`
2. Validar tool-calling con el fallback antes de deploy

---

## 18. Resumen de Archivos Afectados

| Archivo | Acción | Impacto |
|---|---|---|
| `backend/app/config.py` | Modificado | Vars OPENAI → OLLAMA + CHROMA |
| `backend/app/services/vector_store.py` | Reescrito | ChromaDB + pgvector dual backend |
| `backend/app/services/retrieval.py` | Modificado | build_local_search_tools + pgvector retrieval |
| `backend/app/services/ai_agent.py` | Modificado | AsyncOpenAI → httpx Ollama |
| `backend/app/services/tools.py` | Modificado | httpx, pgvector upload, placeholder web search |
| `backend/app/models/document.py` | Modificado | +DocumentEmbedding model |
| `backend/app/models/__init__.py` | Modificado | +DocumentEmbedding export |
| `backend/app/models/project.py` | Modificado | +embeddings relationship |
| `backend/app/main.py` | Modificado | Health check: Ollama + ChromaDB + pgvector |
| `backend/alembic/versions/007_project_embeddings.py` | **Nuevo** | Tabla + índices |
| `backend/requirements.txt` | Modificado | deps swap |
| `backend/tests/test_agent.py` | Modificado | httpx mock |
| `backend/tests/test_tools.py` | Modificado | httpx mock |
| `backend/tests/test_integration.py` | Modificado | pgvector + chromadb fixture |
| `backend/tests/test_e2e.py` | Modificado | ollama mock |

---

*Documento de diseño generado como Phase: Design del change `ollama-local-migration`.*
