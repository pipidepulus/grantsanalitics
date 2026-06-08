# Hybrid Vector Store Specification

## Purpose

Definir los requisitos del motor de almacenamiento vectorial híbrido: ChromaDB local para el conocimiento estático (Metodología Propulsa) y PostgreSQL con pgvector para los documentos de proyecto dinámicos, separando responsabilidades según el ciclo de vida y el scope de los datos.

## ADDED Requirements

### Requirement: ChromaDB knowledge base store

El sistema DEBE usar ChromaDB (`PersistentClient`) como backend permanente para el conocimiento estático (Metodología Propulsa).

#### Scenario: ChromaDB inicialización

- DADO que `CHROMA_DB_PATH=/vector_db` está configurado
- CUANDO la aplicación inicia
- ENTONCES ChromaDB `PersistentClient` se conecta a la ruta configurada
- Y la colección `knowledge_base` ES creada si no existe
- Y la ruta persiste a disco (sobrevive reinicios)

#### Scenario: Búsqueda en Knowledge Base estático

- DADO que ChromaDB tiene la colección `knowledge_base` con datos de la Metodología Propulsa
- CUANDO se envía una consulta (ej: "criterios de elegibilidad")
- ENTONCES ChromaDB retorna los top-k resultados ordenados por similitud
- Y las respuestas no incluyen documentos de algún proyecto específico

#### Scenario: Knowledge base sin datos

- DADO que la colección `knowledge_base` está vacía
- CUANDO se intenta consultar
- ENTONCES se retorna una lista vacía (no se lanza error)

#### Scenario: Bootstrap de Knowledge Base estático

- DADO que la colección `knowledge_base` está vacía
- Y existe un recurso estático de Metodología Propulsa en formato chunked
- CUANDO se ejecuta el bootstrap
- ENTONCES los chunk ES insertado en ChromaDB con embeddings generados por `nomic-embed-text`

### Requirement: pgvector project documents store

El sistema DEBE usar PostgreSQL con la extensión `pgvector` como backend para los documentos de proyecto dinámicos, asegurando aislamiento por `project_id`.

#### Scenario: Tabla document_embeddings creada por migración

- DADO que la migración `007_project_embeddings` se ejecuta
- ENTONCES se crea la tabla `document_embeddings` con:
  - `id` (UUID, PK), `project_id` (UUID FK → projects),
  - `uploaded_doc_id` (UUID FK → uploaded_documents, nullable),
  - `chunk_index` (INT), `content` (TEXT), `embedding` (VECTOR N),
  - `metadata` (JSONB), `created_at` (TIMESTAMPTZ)
- Y se crea índice GIST/pgvector sobre `embedding`
- Y se crea índice GIST sobre `embedding` con operador `vector_cosine_ops`
- Y se crea índice GIN sobre `metadata`

#### Scenario: Búsqueda de documentos de proyecto

- DADO que `document_embeddings` tiene documentos de múltiples proyectos
- CUANDO se busca con `project_id = p-123`, query `query_vec`, max_results = 8
- ENTONCES se retorna: `content, embedding, metadata` donde `project_id = p-123 ORDER BY embedding <=> query_vec LIMIT 8`
- Y documentos de otros proyectos SON excluidos garantidamente por la cláusula WHERE

#### Scenario: Inserción incremental de chunks

- DADO un documento subido al proyecto `p-123`
- CUANDO el chunk 5 del documento se inserta
- ENTONCES se INSERTA en `document_embeddings` con `project_id=p-123, chunk_index=5, content=..., embedding=...`
- Y el documento se marca como indexado en `uploaded_documents.indexing_status = 'indexed'`

#### Scenario: pgvector requiere extensión instalada

- DADO que la aplicación intenta usar pgvector
- CUANDO la extensión `pgvector` no existe en la base de datos
- ENTONCES el sistema lanza un error informativo: `pgvector extension not found. RUN: CREATE EXTENSION IF NOT EXISTS vector;`
- Y la salud check retorna error para pgvector

### Requirement: Dual-tenant vector query orchestration

El sistema DEBE decidir qué backend consultar según el tipo de búsqueda.

#### Scenario: Búsqueda que requiere ambos backends

- DADO que se consulta con conocimiento de metodología y contexto de proyecto
- CUANDO se invoca `search_knowledge_base(query)` Y `retrieve_project_context(project_id, query)`
- ENTONCES se consulta ChromaDB para metodología y pgvector para documentos del proyecto
- Y los resultados se combinan en el prompt del agente

## REMOVED Requirements

### Requirement: Single OpenAI Vector Store for knowledge base
(Reason: Reemplazado por ChromaDB local con embeddings nomic-embed-text)

### Requirement: Single OpenAI Vector Store for project documents
(Reason: Reemplazado por pgvector en PostgreSQL con aislamiento por project_id)

### Requirement: OpenAI file upload and indexing polling
(Reason: Eliminada — pgvector INSERT + ChromaDB add es síncrono directo)

## MODIFIED Requirements

### Requirement: VectorStore client abstraction
El sistema DEVE abstraer el backend vectorial de modo que las capas superiores (agent, tools) llamen a una interfaz uniforme (`search_knowledge_base`, `search_project_documents`) que internamente redirige a ChromaDB o pgvector.
(Previously: Single OpenAI client for all vector operations)

#### Scenario: Interfaz uniforme sobre backend híbrido

- DADO que el sistema se configura con `VECTOR_STORE_MODE=hybrid`
- CUANDO se llama al método `search_knowledge_base(query)`
- ENTONCES internamente se llama a ChromaDB query
- Y la signature del método es idéntica a la versión OpenAI anterior

#### Scenario: Interfaz uniforme sobre pgvector para proyectos

- DADO que el sistema se configura con `VECTOR_STORE_MODE=hybrid`
- CUANDO se llama al método `search_project_documents(project_id, query, max_results)`
- ENTONCES internamente se ejecuta pgvector query con `WHERE project_id = $1 ORDER BY embedding <=> $2 LIMIT $3`
- Y el return type es compatible con la interfaz OpenAI previa (`{content, score, filename}`)
