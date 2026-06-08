# Vector Engine Specification

## Purpose

Definir los requisitos del nuevo motor de embeddings y almacenamiento vectorial local usando `nomic-embed-text` y ChromaDB, reemplazando OpenAI Vector Stores con `text-embedding-3-small`.

## ADDED Requirements

### Requirement: Local Embedding Provider

El sistema DEBE generar embeddings usando `nomic-embed-text` vía Ollama API en lugar de `openai.text_embedding_3_small`.

#### Scenario: Embedding local para documento

- DADO que un usuario sube un documento PDF
- Y ChromaDB está inicializado con embedding function de `nomic-embed-text`
- CUANDO el documento se chunkea y se inserta en ChromaDB
- ENTONCES cada chunk ES persistido con un embedding generado localmente por `ollama/embed/nomic-embed-text`

#### Scenario: Embedding para búsqueda en caliente

- DADO que ChromaDB tiene documentos indexados con `nomic-embed-text`
- CUANDO un usuario consulta "requisitos elegibilidad agricultura"
- ENTONCES la consulta ES embebida usando `nomic-embed-text`
- Y los chunk más similares SON devueltos con la misma función de embedding

### Requirement: ChromaDB Knowledge Base Collection

El sistema DEBE mantener una colección ChromaDB `knowledge_base` para la base de conocimiento estática (Metodología Propulsa).

#### Scenario: Consulta a knowledge base

- DADO que la colección `knowledge_base` existe en ChromaDB con datos
- CUANDO se consulta sin filtro de proyecto
- ENTONCES los documentos de la Metodología Propulsa SON devueltos ordenados por similitud

#### Scenario: knowledge base sin inicialización

- DADO que ChromaDB está vacío o no inicializado
- CUANDO se consulta la colección `knowledge_base`
- ENTONCES se retorna una lista vacía (no se lanza error)

### Requirement: ChromaDB Projects Collection

El sistema DEBE mantener una colección ChromaDB `project_documents` para almacenamiento dinámico de documentos de proyectos y convocatorias.

#### Scenario: Upload de documento a colección de proyecto

- DADO que ChromaDB con colección `project_documents` está activo
- CUANDO se sube un archivo bytes con `project_id=p-123`
- ENTONCES el documento ES almacenado con metadata `{project_id: "p-123", filename: "..."}`
- Y el embedding ES generado vía `nomic-embed-text`

#### Scenario: Duplicado en collection

- DADO que un archivo con mismo nombre y project_id ya existe en `project_documents`
- CUANDO se sube el mismo archivo nuevamente
- ENTONCES el registro existente ES sobreescrito (no duplicado)

### Requirement: ChromaDB persistence path

El sistema DEBE permitir configurar la ruta de almacenamiento de ChromaDB vía la variable `CHROMA_DB_PATH`.

#### Scenario: Ruta personalizada de ChromaDB

- DADO que `CHROMA_DB_PATH=/data/chroma` está configurado
- CUANDO la aplicación inicia
- ENTONCES ChromaDB persiste en `/data/chroma`

#### Scenario: Ruta por defecto de ChromaDB

- DADO que `CHROMA_DB_PATH` no está configurado
- CUANDO la aplicación inicia
- ENTONCES ChromaDB persiste en `/vector_db` por defecto

## REMOVED Requirements

### Requirement: OpenAI Vector Store (knowledge_base)

(Reason: Reemplazado por ChromaDB collection `knowledge_base`)

### Requirement: OpenAI Vector Store (project_documents)

(Reason: Reemplazado por ChromaDB collection `project_documents`)

### Requirement: OpenAI file upload via files.create

(Reason: ChromaDB maneja embeddings y almacenamiento internamente, sin necesidad de API de files)

### Requirement: OpenAI file_search polling

(Reason: ChromaDB query es síncrono; no requiere polling de estatus de indexación)

## MODIFIED Requirements

### Requirement: Vector Store client initialization
El sistema DEBE inicializar el cliente de ChromaDB al inicio, reemplazando el `OpenAI(api_key)` client que usaba `text-embedding-3-small`.
(Previously: initialize OpenAI api client for vector store operations)

#### Scenario: Inicialización de ChromaDB

- DADO que CHROMA_DB_PATH es /vector_db
- Y EMBEDDING_MODEL es nomic-embed-text
- CUANDO la aplicación inicia (app/main.py startup)
- ENTONCES ChromaDBPersistentClient se inicializa con la ruta configurada
- Y la collection `knowledge_base` ES creada si no existe
- Y la collection `project_documents` ES creada si no existe

#### Scenario: Inicialización con rutas separadas

- DADO que CHROMA_KB_PATH y CHROMA_PROJECT_PATH están configurados como rutas separadas
- CUANDO la aplicación inicia
- ENTONCES se crean 2 bases de datos PersistentClient separadas
- Y knowledge_base Y project_documents están aislados físicamente
