# Proposal: Migrate to Local Ollama + Hybrid Vector Stack

## Intent

Eliminar la dependencia de OpenAI (API keys, costos, conectividad) migrando Pipidepulus AI a un stack 100% local: Ollama con `qwen2.5-coder:14b-16k` para generación de texto, `nomic-embed-text` para embeddings, y una arquitectura híbrida de base de datos vectorial — ChromaDB local para el conocimiento estático (Metodología Propulsa) y PostgreSQL con pgvector para los documentos de proyecto dinámicos, asegurando aislamiento garantizado por `project_id`. El objetivo es una herramienta privada, segura y funcional sin dependencias de nube.

## Scope

### In Scope
- Reemplazar OpenAI SDK por Ollama API (`http://localhost:11434`) para generación de texto en `ai_agent.py`
- Migrar embeddings de OpenAI a `nomic-embed-text` vía Ollama
- Arquitectura híbrida de almacenamiento vectorial:
  - ChromaDB local para `knowledge_base` (conocimiento estático / Metodología Propulsa)
  - PostgreSQL + pgvector para `document_embeddings` (documentos de proyecto dinámicos)
- Reescribir `vector_store.py` para soportar ambos backends
- Actualizar `retrieval.py` y `tools.py` para usar ChromaDB y pgvector respectivamente
- Nueva migración Alembic: crear tabla `document_embeddings` con columna `vector` pgvector
- Actualizar uploaded_documents: agregar `embedding_id` como foreign key a `document_embeddings`
- Actualizar `config.py` (nuevas vars: `OLLAMA_BASE_URL`, `OLLAMA_EMBEDDING_MODEL`, `CHROMA_DB_PATH`, `PGVECTOR_COLLECTION`)
- Actualizar `requirements.txt` (eliminar openai, agregar chromadb, pgvector, sqlalchemy[postgresql])
- Actualizar health check: verificar Ollama + ChromaDB + pgvector
- Actualizar tests (mocks de Ollama/ChromaDB/pgvector)

### Out of Scope
- Frontend changes (no requiere cambios)
- Migración de `document_generator.py` (DOCX, no depende de vector)
- Actualización de Dockerfile (solo nota si es crítica)
- Migración de modelos SQL existentes ni migraciones de base de datos estructurales
- Implementación de web search local (deferido)
- Migración de CyRano (evaluación, no OpenAI directo)

## Capabilities

### New Capabilities
- `ollama-inference`: Servicio de inferencia local con Ollama API para generación de respuestas del agente
- `chroma-knowledge-store`: ChromaDB local para almacenamiento vectorial estático (Metodología Propulsa)
- `pgvector-project-store`: PostgreSQL + pgvector para almacenamiento vectorial dinámico de documentos de proyecto con aislamiento por project_id

### Modified Capabilities
- `embedding-provider`: De `openai.text_embedding_3_small` / OpenAI a `nomic-embed-text` vía Ollama, usado por ambos backends
- `retrieval-architecture`: De OpenAI file_search a ChromaDB (KB) + pgvector query (proyectos)
- `health-check`: Verificar Ollama + ChromaDB + pgvector en `/health`

### NEW Security Capabilities
- `vector-isolation`: Aislamiento estricto por `project_id` a nivel SQL (prepared statements, FK CASCADE)
- `file-upload-validation`: Validación doble MIME + Magic Bytes, tamaño máximo, path traversal prevention
- `prompt-injection-protection`: XML delimiters, system prompt hardening, tool allowlist (solo `TOOL_DEFINITIONS`)
- `safe-deserialization`: JSON exclusivo, Pydantic `strict=True, extra='forbid'`, cero pickle/eval
- `vector-sanitization`: Sanitización de NaN/Inf en embeddings antes de INSERT en pgvector

## Approach

### Phase 1 — Dependencias y configuración
- `requirements.txt`: Remover `openai==1.60.0`, agregar `chromadb`, `pgvector`, `sqlalchemy[postgresql]`, `ollama`
- `config.py`: Agregar `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_EMBEDDING_MODEL`, `CHROMA_DB_PATH`, `VECTOR_EMBEDDING_DIM`; manter `DATABASE_URL` pointing to PostgreSQL con pgvector
- Verificar pgvector extension disponible en el PostgreSQL activo

### Phase 2 — Nueva tabla de embeddings (Alembic)
- Migración `007_project_embeddings.py`: crear tabla `document_embeddings`
  - `id` (UUID PK), `project_id` (UUID FK → projects), `uploaded_doc_id` (UUID FK → uploaded_documents, nullable),
  - `chunk_index` (INT), `content` (TEXT), `embedding` (VECTOR N dim),
  - `metadata` (JSONB para filename, source, tags), `created_at` (TIMESTAMPTZ)
  - Índice GiST/pgvector sobre columna `embedding` para búsqueda eficiente
  - Índice GIN sobre `metadata` para filtrado rápido por project_id
  - Indexación de `document_embeddings.embedding` con INDEX opclass vector_cosine_ops

### Phase 3 — Vector Store híbrido (`vector_store.py`)
- `search_knowledge_base()`: ChromaDB collection `knowledge_base`, sin filtros
- `search_projects_store()`: pgvector query con `cosine_distance(embedding, :query_vec)`, WHERE `project_id = :project_id`, ORDER BY distancia, LIMIT
- `upload_bytes_to_projects_store()`:
  - Chunkear documento
  - Embedding cada chunk con `nomic-embed-text`
  - INSERT cada chunk + embedding en `document_embeddings` con `project_id`
  - Marcar documento como indexado
- `upload_bytes_to_knowledge_base()`: nuevo endpoint → ChromaDB (sin project_id)
- Upload de KB estática durante init (migrar datos existentes de OpenAI a ChromaDB)

### Phase 4 — Retrieval (`retrieval.py`)
- `build_local_search_tools()`: retornar `{chroma_query: ... , pgvector_query: ...}`
- `retrieve_project_context()`: pgvector search con `WHERE project_id = :pid ORDER BY embedding <=> :query_vec LIMIT :max_results`
- Eliminar toda dependencia de OpenAI client

### Phase 5 — Agente (`ai_agent.py`)
- `AsyncOpenAI` → `httpx` POST `/v1/chat/completions` vía Ollama
- `qwen2.5-coder:14b-16k` configurable vía `OLLAMA_MODEL`
- Tool-calling vía Ollama `tools` parameter
- Inicializar ambos stores al arranque

### Phase 6 — Tools (`tools.py`)
- `search_funding_calls`: placeholder (deferred)
- `extract_requirements`, `calculate_budget`, etc.: sin cambios (lógica local)
- Upload → delegar a `vector_store.upload_bytes_to_projects_store()`
- Eliminar `AsyncOpenAI` import

### Phase 7 — Health check y tests
- `main.py` `/health`: verificar Ollama, ChromaDB, pgvector
- Tests: mocks de Ollama, ChromaDB, y pgvector (pytest fixtures con tabla efímera o `pgvector` mock)

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/config.py` | Modified | Vars: `OPENAI_*` → `OLLAMA_*`, `CHROMA_DB_PATH`, `VECTOR_EMBEDDING_DIM` |
| `app/services/vector_store.py` | Rewritten | Dual backend: ChromaDB (KB) + pgvector (proyectos) |
| `app/services/retrieval.py` | Rewritten | ChromaDB query + pgvector distance search |
| `app/services/ai_agent.py` | Rewritten | AsyncOpenAI → Ollama API |
| `app/services/tools.py` | Modified | Embedding + upload; tools stay local |
| `app/main.py` | Modified | Health check: Ollama + ChromaDB + pgvector |
| `app/models/document.py` | Modified | `UploadedDocument` agrega `embedding_id` |
| `app/models/__init__.py` | Modified | Export `DocumentEmbedding` |
| `backend/requirements.txt` | Modified | openai → chromadb + pgvector + ollama |
| `backend/alembic/versions/007_project_embeddings.py` | **New** | Tabla `document_embeddings` con vector N |
| `tests/*.py` | Modified | Mocks de Ollama/ChromaDB/pgvector |
| New `specs/security/spec.md` | **New** | Security requirements: vector isolation, file upload, prompt injection, safe deserialization |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `qwen2.5-coder:14b` no soporta tool calling completamente | High | Tener fallback a `phi3` o `llama3.1` en config; pre-validar antes de deploy |
| pgvector requiere extensión en PostgreSQL | Medium | Verificar instalación en init; script de auto-instalación de extensión |
| Migración de datos KB de OpenAI → ChromaDB | Med | Script de bootstrap: export desde VS OpenAI, importar a ChromaDB |
| Calidad de `nomic-embed-text` vs OpenAI | Medium | Usar embedding dim 768; ajustar `n_results`; validar con dataset reales |
| pgvector performance con datasets grandes | Med | Índices HNSW (`create index ... using hnsw (embedding vector_cos_ops)`); partición por proyecto si necesario |
| Formato de respuesta Ollama vs OpenAI | Med | `/v1/chat/completions` 99% compatible; testing exhaustivo post-migración |

## Rollback Plan

1. Mantener `vector_store.py` original como `vector_store_openai.py` (backup)
2. Env var `VECTOR_STORE_MODE=hybrid|openai` como feature flag
3. Si pgvector falla: script de reconstrucción de índice al iniciar
4. Si tool-calling de qwen2.5-coder falla: rollback a `phi3` o `llama3.1`

## Dependencies

- Servidor: Ollama corriendo (`ollama serve` en `localhost:11434`)
- Modelos: `ollama pull qwen2.5-coder:14b` y `ollama pull nomic-embed-text`
- PostgreSQL: con extensión `pgvector` instalada
- ChromaDB: local, sin servidor externo
- RAM: Mínimo 8GB (16GB recomendado, pgvector consume memória para índices)
- Almacenamiento: espacio para ChromaDB (`/vector_db`) + base de datos existente

## Success Criteria

- [ ] Health check `/health` retorna OK para Ollama, ChromaDB y pgvector
- [ ] Generación de texto con `qwen2.5-coder:14b` funciona sin OpenAI
- [ ] Upload de documentos → pgvector con embeddings `nomic-embed-text`, filtrado por `project_id`
- [ ] `knowledge_base` en ChromaDB consultable sin filtros
- [ ] Cero contaminación cruzada entre proyectos (WHERE project_id funciona)
- [ ] pgvector índice responde en <100ms para <10k chunks por proyecto
- [ ] Tool-calling con `qwen2.5-coder:14b` funciona para 3+ tools
- [ ] Tests de integración pasan con mocks de Ollama/ChromaDB/pgvector
- [ ] Cero imports de `openai` en código fuente del backend
- [ ] Migración `007` crea tabla + índices correctamente
- [ ] `WHERE project_id = $1` en TODAS las queries pgvector (cero string interpolation)
- [ ] Archivos validados doblemente con `python-magic` antes de procesamiento
- [ ] Archivos < 50MB y guardados con UUID (cero path traversal)
- [ ] Embeddings sanitizados (NaN/Inf → 0.0) antes de INSERT pgvector
- [ ] Tool dispatcher solo acepta herramientas de `TOOL_DEFINITIONS`
- [ ] System prompt incluye hardening contra prompt injection
