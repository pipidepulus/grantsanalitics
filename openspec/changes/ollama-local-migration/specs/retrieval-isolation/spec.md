# Retrieval and Isolation Specification

## Purpose

Definir los requisitos para la capa de búsqueda y recuperación (retrieval) usando dos backends distintos: ChromaDB para conocimiento estático y pgvector para documentos de proyecto dinámicos, con aislamiento garantizado por `project_id` a nivel de base de datos.

## ADDED Requirements

### Requirement: ChromaDB static knowledge retrieval

El sistema DEVE proporcionar `build_local_search_tools()` que configure un query sobre la colección ChromaDB `knowledge_base` para búsquedas de conocimiento estático.

#### Scenario: Búsqueda sin proyecto activo

- DADO que no hay proyecto activo (`project_id = None`)
- CUANDO se llama `build_local_search_tools(project_id=None)`
- ENTONCES se retorna configuración para consultar **solo** ChromaDB `knowledge_base`

#### Scenario: Búsqueda con proyecto activo — KB

- DADO que hay un proyecto activo
- CUANDO se llama `build_local_search_tools(project_id=p-123)`
- ENTONCES se retorna configuración para consultar ChromaDB `knowledge_base`
- Y ChromaDB se consulta sin filtros (esknowledge_base, no hay project isolation needed)

### Requirement: pgvector dynamic project retrieval

El sistema DEVE proporcionar `retrieve_project_context(project_id, query, max_results)` que consulta la tabla `document_embeddings` con filtrado estricto por `project_id`.

#### Scenario: Contexto de proyecto para consulta

- DADO que un usuario interactúa con proyecto `p-123`
- Y `document_embeddings` tiene registros con `project_id = p-123`
- CUANDO se llama `retrieve_project_context("p-123", "requisitos elegibilidad", 8)`
- ENTONCES se ejecuta `SELECT content, metadata FROM document_embeddings WHERE project_id = 'p-123' ORDER BY embedding <=> query_vec LIMIT 8`
- Y se retornan chunk formateados como `<project_documents>...</project_documents>`
- Y solo documentos de `p-123` SON incluidos

#### Scenario: Sin documentos para proyecto en pgvector

- DADO que `document_embeddings` no tiene registros para `p-123`
- CUANDO se llama `retrieve_project_context("p-123", "cualquier consulta", 8)`
- ENTONCES la query pgvector retorna 0 filas
- Y se retorna cadena vacía (no error)

#### Scenario: Consulta a múltiples proyectos simultáneos

- DADO que `document_embeddings` tiene documentos de `p-1`, `p-2`, `p-3`
- CUANDO se consulta con `project_id = p-2`
- ENTONCES **solo** documentos de `p-2` SON retornados
- Y documentos de `p-1` y `p-3` SON excluidos por la cláusula WHERE (garantía de BD relacional)

### Requirement: Dual-backend retrieval orchestration

El sistema DEVE orquestar ambas consultas (ChromaDB + pgvector) cuando se necesita contexto de metodología y documentos de proyecto simultáneamente.

#### Scenario: Consulta dual (KB + proyectos)

- DADO que hay un proyecto activo y se consulta algo que requiere metodología
- CUANDO la orquestación de retrieval se ejecuta
- ENTONCES se realizan dos consultas en paralelo:
  - ChromaDB `knowledge_base` query con `nomic-embed-text`
  - pgvector `document_embeddings` query con filtro `project_id`
- Y los resultados se combinan antes de inyectar en el prompt del agente

#### Scenario: Consulta solo KB

- DADO que consulta no requiere documentos de proyecto
- CUANDO se invoca retrieval
- ENTONCES solo ChromaDB es consultado
- Y pgvector no es llamado (ahorro de query a BD)

## REMOVED Requirements

### Requirement: OpenAI Vector Store file_search (KB)

(Reason: Replaced by ChromaDB collection `knowledge_base` query)

### Requirement: OpenAI Vector Store file_search filter (project isolation)

(Reason: Replaced by pgvector WHERE project_id clause — relational guarantee vs unreliable file attribute filtering)

### Requirement: OpenAI Vector Store file_upload_polling

(Reason: pgvector INSERT is synchronous; no polling needed)

## MODIFIED Requirements

### Requirement: Project-scoped document isolation

El sistema DEVE lograr aislamiento por proyecto mediante una cláusula `WHERE project_id = $1` en la consulta pgvector, reemplazando el mecanismo de OpenAI que filtraba por vector store file attributes (poco confiable).
(Previously: Use OpenAI file attribute filters for project isolation)

#### Scenario: Aislamiento garantizado a nivel SQL

- DADO que `document_embeddings` contiene registros de múltiples proyectos
- CUANDO un proyecto `p-A` consulta su documento
- ENTONCES la query SQL tiene `WHERE project_id = 'p-A'`
- Lo cual garantiza (por ser cláusula SQL) que ningun documento de otro proyecto pueda ser leído

#### Scenario: Concurrent project access

- DADO que dos usuarios de proyectos diferentes consultan simultáneamente
- ENTONCES cada query pgvector tiene su propio WHERE project_id
- Y no hay riesgo de contaminación cruzada entre sesiones
