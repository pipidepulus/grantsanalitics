# Pipidepulus AI — Documentación Técnica

## Índice

1. [Visión General](#visión-general)
2. [Arquitectura del Sistema](#arquitectura-del-sistema)
3. [Flujo de Datos](#flujo-de-datos)
4. [Modelo de Datos](#modelo-de-datos)
5. [Pipeline del Agente AI](#pipeline-del-agente-ai)
6. [Flujo de Trabajo del Usuario](#flujo-de-trabajo-del-usuario)
7. [Estructura del Proyecto](#estructura-del-proyecto)
8. [API Endpoints](#api-endpoints)
9. [Componentes Frontend](#componentes-frontend)
10. [Tests y Resultados](#tests-y-resultados)
11. [Comandos para Arrancar la Aplicación](#comandos-para-arrancar-la-aplicación)
12. [Configuración del Entorno Local (WSL)](#configuración-del-entorno-local-wsl)

---

## Visión General

**Pipidepulus AI** es una plataforma de ingeniería de proyectos que automatiza la búsqueda, análisis, formulación y optimización de propuestas para convocatorias de financiamiento (grants/subvenciones) utilizando la Metodología Propulsa.

```mermaid
graph LR
    subgraph Usuario
        U[Proponente]
    end

    subgraph "Pipidepulus AI"
        FE["Frontend<br/>Next.js 16"]
        BE["Backend<br/>FastAPI"]
        DB[(PostgreSQL)]
        AI["OpenAI<br/>Responses API"]
        VS1["Vector Store<br/>Knowledge Base"]
        VS2["Vector Store<br/>Projects"]
    end

    U --> FE
    FE -->|REST API| BE
    BE --> DB
    BE --> AI
    AI --> VS1
    AI --> VS2
```

---

## Arquitectura del Sistema

```mermaid
graph TB
    subgraph "Frontend — Next.js 16"
        PAGE["page.tsx<br/>App Shell"]
        SIDE["Sidebar<br/>Navegación"]
        CHAT["ChatPanel<br/>Conversación"]
        REVIEW["ReviewPanel<br/>Modo Revisión"]
        API_CLIENT["lib/api.ts<br/>Cliente HTTP"]

        PAGE --> SIDE
        PAGE --> CHAT
        PAGE --> REVIEW
        CHAT --> API_CLIENT
        SIDE --> API_CLIENT
        REVIEW --> API_CLIENT
    end

    subgraph "Backend — FastAPI"
        MAIN["main.py<br/>App Entry"]
        
        subgraph "API Routes"
            R_CHAT["/api/chat"]
            R_PROJ["/api/projects"]
            R_USER["/api/users"]
            R_DOCS["/api/documents"]
            R_CALL["/api/calls"]
        end

        subgraph "Services"
            AGENT["ai_agent.py<br/>Orquestador"]
            TOOLS["tools.py<br/>Function Tools"]
            VSTORE["vector_store.py<br/>Vector Store Svc"]
            DOCGEN["document_generator.py"]
        end

        subgraph "Core"
            PROMPTS["prompts.py<br/>System Prompt<br/>+ Intent Schema"]
            CONFIG["config.py<br/>Settings"]
        end

        subgraph "Data Layer"
            MODELS["Models<br/>SQLAlchemy"]
            SCHEMAS["Schemas<br/>Pydantic"]
            DATABASE["database.py<br/>Session"]
        end

        MAIN --> R_CHAT
        MAIN --> R_PROJ
        MAIN --> R_USER
        MAIN --> R_DOCS
        MAIN --> R_CALL

        R_CHAT --> AGENT
        AGENT --> TOOLS
        AGENT --> PROMPTS
        TOOLS --> VSTORE
        TOOLS --> DOCGEN

        R_PROJ --> MODELS
        R_USER --> MODELS
        R_DOCS --> MODELS
        R_CALL --> VSTORE

        MODELS --> DATABASE
    end

    subgraph "External"
        OPENAI["OpenAI API<br/>gpt-5-mini"]
        VS_KB["Vector Store<br/>Metodología Propulsa"]
        VS_PR["Vector Store<br/>Proyectos & Docs"]
        PG[(PostgreSQL 16)]
    end

    API_CLIENT -->|HTTP| MAIN
    AGENT --> OPENAI
    OPENAI --> VS_KB
    OPENAI --> VS_PR
    VSTORE --> VS_PR
    DATABASE --> PG
```

---

## Flujo de Datos

### Flujo de Chat Completo (SSE Streaming)

```mermaid
sequenceDiagram
    actor User as Usuario
    participant FE as Frontend
    participant API as FastAPI
    participant Agent as AI Agent
    participant OAI as OpenAI Responses API
    participant VS as Vector Stores
    participant DB as PostgreSQL

    User->>FE: Escribe mensaje
    FE->>API: POST /api/chat/stream (SSE)
    API->>DB: Guardar mensaje usuario
    API->>Agent: process_chat_message_stream()

    Agent->>Agent: Build message history
    Agent->>OAI: responses.create()<br/>model=gpt-5-mini<br/>tools=[functions, file_search, web_search]

    alt Tool Calls requeridos
        OAI-->>Agent: function_call responses
        
        loop Para cada tool call
            Agent->>Agent: Ejecutar handler local
            Note over Agent: search_funding_calls<br/>extract_requirements<br/>calculate_budget<br/>generate_word_document<br/>run_diagnostic<br/>save_project_data<br/>save_to_project_memory
        end

        Agent->>OAI: responses.create()<br/>con tool results
    end

    alt file_search activado
        OAI->>VS: Buscar en Knowledge Base
        VS-->>OAI: Resultados metodología
        OAI->>VS: Buscar en Projects Store
        VS-->>OAI: Proyectos previos
    end

    OAI-->>Agent: Respuesta final con texto

    Agent->>Agent: Extraer Cyrano score (si aplica)
    Agent-->>API: SSE events (meta, tool, delta, done)
    API-->>FE: Stream chunks vía SSE
    Agent->>DB: Guardar mensaje asistente
    Agent->>DB: Actualizar proyecto (si score)
    FE-->>User: Renderizar respuesta markdown en tiempo real
```

### Flujo de Generación de Documento

```mermaid
sequenceDiagram
    actor User as Usuario
    participant Agent as AI Agent
    participant Tool as generate_word_document
    participant DB as PostgreSQL

    User->>Agent: "Genera el documento Word"
    Agent->>Tool: handle_generate_word_document()
    
    Tool->>DB: Query Project by ID
    
    alt cyrano_score < 95.01
        Tool-->>Agent: BLOQUEADO<br/>"Puntaje insuficiente"
        Agent-->>User: "El proyecto necesita ≥ 95.01"
    else cyrano_score >= 95.01
        Tool->>Tool: Crear Document (python-docx)
        Tool->>Tool: Agregar secciones:<br/>1. Problema<br/>2. Árbol de Problemas<br/>3. Objetivos<br/>4. Cadena de Valor<br/>5. Cronograma<br/>6. Presupuesto
        Tool->>DB: Guardar GeneratedDoc (binary)
        Tool-->>Agent: {filename, version, doc_id}
        Agent-->>User: "Documento generado: v1.docx"
    end
```

### Flujo de Subida de Documentos

```mermaid
sequenceDiagram
    actor User as Usuario
    participant FE as Frontend
    participant API as FastAPI
    participant DB as PostgreSQL
    participant VS as Vector Store Proyectos

    User->>FE: Click 📎 + seleccionar archivo
    FE->>FE: Preview del archivo pendiente
    User->>FE: Enviar mensaje (con adjuntos)
    FE->>API: POST /api/documents/upload<br/>(multipart/form-data)
    API->>API: Validar tipo (PDF/DOCX/DOC/TXT/MD)<br/>y tamaño (≤ 20MB)
    API->>DB: Guardar UploadedDocument (binary)
    API->>VS: Subir al Vector Store de Proyectos
    VS-->>API: vector_store_file_id
    API->>DB: Actualizar con vector_store_file_id
    API-->>FE: {id, filename, status}
    FE-->>User: ✓ Archivo subido
```

### Flujo de Exportación de Conversación

```mermaid
sequenceDiagram
    actor User as Usuario
    participant FE as Frontend
    participant API as FastAPI
    participant DB as PostgreSQL

    User->>FE: Click ⬇ (botón exportar)
    FE->>API: GET /api/chat/conversations/:userId/:convId/export
    API->>DB: Query Conversation + Messages
    API->>API: Generar .docx con python-docx<br/>(título, timestamps, mensajes formateados)
    API-->>FE: StreamingResponse (application/docx)<br/>Content-Disposition: attachment
    FE-->>User: Descarga automática del archivo .docx
```

---

## Modelo de Datos

```mermaid
erDiagram
    USERS {
        uuid id PK
        varchar name
        varchar email UK
        varchar organization
        varchar sector
        varchar territory
        jsonb preferences
        timestamp created_at
        timestamp updated_at
    }

    PROJECTS {
        uuid id PK
        uuid user_id FK
        varchar title
        varchar status
        float cyrano_score
        varchar language
        jsonb json_data
        text problem_definition
        jsonb problem_tree
        jsonb objectives_tree
        jsonb value_chain
        jsonb timeline
        jsonb budget
        uuid call_spec_id FK
        timestamp created_at
        timestamp updated_at
    }

    CALL_SPECS {
        uuid id PK
        varchar title
        text source_url
        jsonb extracted_requirements
        text eligibility_criteria
        varchar max_amount
        varchar counterpart_required
        varchar deadline
        jsonb mandatory_sections
        text raw_text
        timestamp created_at
    }

    GENERATED_DOCS {
        uuid id PK
        uuid project_id FK
        varchar filename
        bytea binary_file
        int version_number
        timestamp created_at
    }

    CONVERSATIONS {
        uuid id PK
        uuid user_id FK
        uuid project_id FK
        varchar title
        timestamp created_at
        timestamp updated_at
    }

    MESSAGES {
        uuid id PK
        uuid conversation_id FK
        varchar role
        text content
        jsonb tool_calls
        timestamp created_at
    }

    UPLOADED_DOCUMENTS {
        uuid id PK
        uuid project_id FK
        uuid user_id FK
        varchar filename
        varchar content_type
        bytea file_data
        int file_size
        varchar vector_store_file_id
        jsonb metadata
        timestamp created_at
    }

    USERS ||--o{ PROJECTS : "crea"
    USERS ||--o{ CONVERSATIONS : "inicia"
    USERS ||--o{ UPLOADED_DOCUMENTS : "sube"
    PROJECTS ||--o{ GENERATED_DOCS : "genera"
    PROJECTS ||--o{ UPLOADED_DOCUMENTS : "adjunto a"
    PROJECTS }o--o| CALL_SPECS : "vinculado a"
    CONVERSATIONS ||--o{ MESSAGES : "contiene"
    CONVERSATIONS }o--o| PROJECTS : "sobre"
```

---

## Pipeline del Agente AI

### Ciclo de Resolución de Tool Calls

```mermaid
flowchart TD
    START([Usuario envía mensaje]) --> BUILD[Construir historial<br/>+ System Prompt]
    BUILD --> CALL[OpenAI responses.create<br/>model=gpt-5-mini<br/>tools=functions+file_search+web_search]
    CALL --> CHECK{¿Hay<br/>function_calls?}
    
    CHECK -->|Sí| DISPATCH[Dispatch a handler local]
    DISPATCH --> EXEC[Ejecutar tool handler]
    EXEC --> COLLECT[Recopilar resultados]
    COLLECT --> CONTINUE[responses.create<br/>con tool results]
    CONTINUE --> CHECK

    CHECK -->|No| EXTRACT[Extraer texto final]
    EXTRACT --> SCORE{¿Se ejecutó<br/>run_diagnostic?}
    
    SCORE -->|Sí| PARSE[Extraer Cyrano score<br/>con regex]
    PARSE --> SAVE
    SCORE -->|No| SAVE[Guardar mensaje<br/>en PostgreSQL]
    
    SAVE --> RETURN([Retornar ChatResponse])

    style START fill:#6366f1,color:#fff
    style RETURN fill:#22c55e,color:#fff
```

### Metodología Propulsa — Los 6 Pasos

```mermaid
flowchart LR
    subgraph "Módulo A: DETECTA"
        A1[Web Scanning<br/>search_funding_calls]
        A2[Data Extraction<br/>extract_requirements]
    end

    subgraph "Módulo B: CREA"
        B1["1. Problema"]
        B2["2. Árbol de<br/>Problemas"]
        B3["3. Objetivos<br/>SMART"]
        B4["4. Cadena<br/>de Valor"]
        B5["5. Cronograma"]
        B6["6. Presupuesto"]
        
        B1 --> B2 --> B3 --> B4 --> B5 --> B6
    end

    subgraph "Módulo C: VALIDA"
        C1["run_diagnostic<br/>Cyrano 95+"]
        C2{Score ≥ 95.01?}
        C3["generate_word_document<br/>Exportar .docx"]
        C4["Modo Consultor<br/>Analizar brechas"]
        
        C1 --> C2
        C2 -->|Sí| C3
        C2 -->|No| C4
        C4 -.->|Iterar| B1
    end

    A1 --> A2
    A2 --> B1
    B6 --> C1

    style C3 fill:#22c55e,color:#fff
    style C4 fill:#f59e0b,color:#000
```

### Intent Schema del Agente

```mermaid
mindmap
  root((Pipidepulus AI<br/>Intent Schema))
    Objective
      Guiar creación de proyectos
      Superar umbral Cyrano 95+
      Coherencia problema-objetivos-presupuesto
    Constraints
      No alucinar términos metodológicos
      No aprobar score < 95.01
      Citar fuentes de convocatorias
      Equivalencia bilingüe ES/EN
    Tools
      search_funding_calls
      extract_requirements
      calculate_budget
      generate_word_document
      run_diagnostic
      save_project_data
      save_to_project_memory
    Glossary
      Árbol de problemas
      Cadena de valor
      Contrapartida
      Hito / Indicador / Meta
    Stop Rules
      Bloquear export si < 95.01
      Entrar modo consultor si falla
```

---

## Flujo de Trabajo del Usuario

```mermaid
stateDiagram-v2
    [*] --> NuevaConversacion: Abrir app

    NuevaConversacion --> BuscarConvocatorias: "Busca convocatorias de..."
    NuevaConversacion --> SubirDocumento: Subir PDF de convocatoria
    NuevaConversacion --> CrearProyecto: "Quiero crear un proyecto"

    BuscarConvocatorias --> AnalizarResultados
    SubirDocumento --> ExtraerRequisitos
    AnalizarResultados --> CrearProyecto
    AnalizarResultados --> ExportarChat: Exportar a Word
    ExtraerRequisitos --> CrearProyecto

    CrearProyecto --> DefinirProblema
    
    state "Módulo B: Metodología Propulsa" as MetPropulsa {
        DefinirProblema --> ArbolProblemas
        ArbolProblemas --> ObjetivosSMART
        ObjetivosSMART --> CadenaValor
        CadenaValor --> Cronograma
        Cronograma --> Presupuesto
    }

    Presupuesto --> EjecutarDiagnostico

    state "Módulo C: Validación Cyrano" as Validacion {
        EjecutarDiagnostico --> EvaluarScore
        EvaluarScore --> Aprobado: Score ≥ 95.01
        EvaluarScore --> EnRevision: Score < 95.01
        EnRevision --> ModoConsultor
        ModoConsultor --> DefinirProblema: Iterar mejoras
    }

    Aprobado --> GenerarDocumento
    GenerarDocumento --> DescargarWord
    DescargarWord --> ExportarChat: Exportar conversación
    ExportarChat --> [*]
    DescargarWord --> [*]
```

---

## Estructura del Proyecto

```mermaid
graph TD
    subgraph "grantsanalitics/"
        ENV[".env"]
        DC["docker-compose.yml"]
        
        subgraph "backend/"
            MAIN_PY["app/main.py"]
            CONFIG_PY["app/config.py"]
            DB_PY["app/database.py"]
            
            subgraph "api/routes/"
                CHAT_R["chat.py"]
                PROJ_R["projects.py"]
                USER_R["users.py"]
                DOCS_R["documents.py"]
                CALL_R["calls.py"]
            end
            
            subgraph "services/"
                AI_AGENT["ai_agent.py"]
                TOOLS_S["tools.py"]
                VS_SVC["vector_store.py"]
                DOC_GEN["document_generator.py"]
            end
            
            subgraph "core/"
                PROMPTS_C["prompts.py"]
            end
            
            subgraph "models/"
                M_USER["user.py"]
                M_PROJ["project.py"]
                M_DOC["document.py"]
                M_CALL["call_spec.py"]
                M_CONV["conversation.py"]
            end

            subgraph "alembic/"
                ALM_ENV["env.py"]
                ALM_V1["versions/001_initial_schema.py"]
                ALM_V2["versions/002_add_uploaded_documents.py"]
            end
        end
        
        subgraph "frontend/"
            subgraph "src/app/"
                LAYOUT["layout.tsx"]
                PAGE_TSX["page.tsx"]
                CSS["globals.css"]
            end
            subgraph "src/components/"
                SIDEBAR_C["Sidebar.tsx"]
                CHATPANEL["ChatPanel.tsx"]
                REVIEWPANEL["ReviewPanel.tsx"]
            end
            subgraph "src/lib/"
                API_TS["api.ts"]
                TYPES_TS["types.ts"]
            end
        end
    end
```

---

## API Endpoints

```mermaid
graph LR
    subgraph "Chat"
        POST_CHAT["POST /api/chat"]
        POST_STREAM["POST /api/chat/stream"]
        GET_CONVS["GET /api/chat/conversations/:userId"]
        GET_CONV["GET /api/chat/conversations/:userId/:convId"]
        DEL_CONV["DELETE /api/chat/conversations/:userId/:convId"]
        GET_EXPORT["GET /api/chat/conversations/:userId/:convId/export"]
    end

    subgraph "Projects"
        POST_PROJ["POST /api/projects"]
        GET_PROJS["GET /api/projects?user_id="]
        GET_PROJ["GET /api/projects/:id"]
        PATCH_PROJ["PATCH /api/projects/:id"]
        DEL_PROJ["DELETE /api/projects/:id"]
    end

    subgraph "Users"
        POST_USER["POST /api/users"]
        GET_USER["GET /api/users/:id"]
        PATCH_USER["PATCH /api/users/:id"]
    end

    subgraph "Documents"
        POST_UPLOAD_DOC["POST /api/documents/upload"]
        GET_PDOCS["GET /api/documents/project/:id"]
        GET_ALL_DOCS["GET /api/documents/project/:id/all"]
        GET_DL["GET /api/documents/:id/download"]
    end

    subgraph "Call Specs"
        POST_CALL["POST /api/calls"]
        GET_CALLS["GET /api/calls"]
        GET_CALL["GET /api/calls/:id"]
        POST_UPLOAD["POST /api/calls/:id/upload"]
    end
```

### Protocolo SSE (Server-Sent Events)

El endpoint `POST /api/chat/stream` envía eventos SSE con el formato `data: {json}\n\n`:

| Evento | Payload | Descripción |
|--------|---------|-------------|
| `meta` | `{type: "meta", conversation_id}` | ID de conversación (enviado primero) |
| `tool` | `{type: "tool", name, status}` | Estado de ejecución de herramientas |
| `delta` | `{type: "delta", content}` | Fragmento de texto (chunks de 12 chars) |
| `done` | `{type: "done", conversation_id, message_id, tool_calls, cyrano_score}` | Fin del mensaje |
| `error` | `{type: "error", content}` | Error en el procesamiento |

El stream termina con `data: [DONE]\n\n`.

---

## Componentes Frontend

```mermaid
graph TB
    subgraph "Layout (layout.tsx)"
        subgraph "Page (page.tsx)"
            SIDEBAR["Sidebar"]
            CHATPANEL_C["ChatPanel"]
            REVIEWPANEL_C["ReviewPanel"]
        end
    end

    SIDEBAR -->|"onProjectSelect"| CHATPANEL_C
    SIDEBAR -->|"onConversationSelect"| CHATPANEL_C
    SIDEBAR -->|"onToggleReview"| REVIEWPANEL_C

    subgraph "Sidebar Features"
        S1["🏆 Cyrano Score Badge"]
        S2["💬 Conversaciones (+ eliminar)"]
        S3["📁 Bóveda de Proyectos"]
        S4["🔍 Radar de Convocatorias"]
        S5["👤 Perfil Proponente"]
        S6["📝 Modo Revisión Toggle"]
        S7["📄 Documentos del Proyecto<br/>(subidos + generados)"]
    end

    subgraph "ChatPanel Features"
        C1["💬 Mensajes con Markdown"]
        C2["⚡ Tool calls indicator"]
        C3["⏳ Loading + Streaming SSE"]
        C4["📝 Auto-resize textarea"]
        C5["📎 Adjuntar documentos"]
        C6["⬇️ Exportar conversación a Word"]
    end

    subgraph "ReviewPanel Tabs"
        R1["📊 Resumen"]
        R2["❗ Problema"]
        R3["🎯 Objetivos"]
        R4["🔗 Cadena de Valor"]
        R5["📅 Cronograma"]
        R6["💰 Presupuesto"]
        R7["📄 Documentos"]
    end

    SIDEBAR --> S1 & S2 & S3 & S4 & S5 & S6 & S7
    CHATPANEL_C --> C1 & C2 & C3 & C4 & C5 & C6
    REVIEWPANEL_C --> R1 & R2 & R3 & R4 & R5 & R6 & R7
```

---

## Tests y Resultados

### Infraestructura de Tests

- **Framework**: pytest 8.4.2 + pytest-asyncio 0.24.0
- **Base de datos de test**: SQLite en memoria (aislamiento total por test)
- **HTTP Client**: FastAPI TestClient (httpx)
- **Mocking**: unittest.mock para dependencias externas (OpenAI, vector stores)

### Ejecución

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/ -v
```

### Resultados: 81 tests passed, 0 failed (1.08s)

```
tests/test_agent.py    — 13 passed  (Agent orchestration)
tests/test_api.py      — 17 passed  (API integration)
tests/test_e2e.py      —  4 passed  (End-to-end flows)
tests/test_models.py   — 14 passed  (Database models)
tests/test_prompts.py  — 14 passed  (Prompts & config)
tests/test_tools.py    — 19 passed  (Tool handlers)
─────────────────────────────────────────────────
TOTAL                    81 passed   ✅
```

### Cobertura por Categoría

```mermaid
pie title Distribución de Tests (81 total)
    "Unit — Models" : 14
    "Unit — Tools" : 19
    "Unit — Prompts & Config" : 14
    "Unit — Agent" : 13
    "Integration — API" : 17
    "E2E — Workflows" : 4
```

#### Tests Unitarios (60 tests)

| Archivo | Tests | Descripción |
|---------|-------|-------------|
| `test_models.py` | 14 | Creación de modelos, campos opcionales, relaciones, unicidad de email, mensajes con tool_calls |
| `test_tools.py` | 19 | 7 tool handlers: search_funding_calls (mock vector store), extract_requirements, calculate_budget (validación completa), generate_word_document (bloqueo Cyrano, generación .docx), run_diagnostic, save_project_data, save_to_project_memory |
| `test_prompts.py` | 14 | Estructura XML del system prompt, secciones de metodología, glosario, umbral Cyrano 95.01, prompt de diagnóstico, configuración de Settings |
| `test_agent.py` | 13 | get_or_create_conversation, build_message_history, _extract_cyrano_score (6 escenarios regex), TOOL_HANDLERS registry |

#### Tests de Integración (17 tests)

| Endpoint | Tests | Operaciones |
|----------|-------|-------------|
| `/api/users` | 4 | POST (201), GET, GET 404, PATCH |
| `/api/projects` | 6 | POST (201), GET list, GET by ID, GET 404, PATCH, PATCH methodology |
| `/api/documents` | 2 | GET list (vacío), GET download 404 |
| `/api/calls` | 3 | POST (201), GET list, GET by ID |
| `/api/chat` | 2 | POST 422 (validación), GET conversations |
| `/api/chat` (stream) | - | POST /chat/stream (SSE streaming) |
| `/api/chat` (export) | - | GET /conversations/:userId/:convId/export (Word) |
| `/api/health` | 1 | GET health check |", "oldString": "| `/api/chat` | 2 | POST 422 (validación), GET conversations |\n| `/api/health` | 1 | GET health check |

#### Tests E2E (4 tests)

| Test | Descripción |
|------|-------------|
| `test_full_project_lifecycle` | Flujo completo: crear usuario → crear proyecto → completar metodología → validar score Cyrano → generar documento Word → descargar |
| `test_document_blocked_below_threshold` | Verifica que score < 95.01 bloquea la exportación |
| `test_call_spec_to_project_flow` | Crear convocatoria y verificar persistencia |
| `test_conversation_persistence` | Listar conversaciones de un usuario |

---

## Comandos para Arrancar la Aplicación

### Opción 1: Con Docker Compose (recomendado)

```bash
# Desde la raíz del proyecto
cd /home/daniel/grantsanalitics

# Configurar variables de entorno
cp .env.example .env  # Editar con tus claves reales de OpenAI

# Levantar todos los servicios
docker-compose up -d

# Verificar que están corriendo
docker-compose ps

# Ver logs
docker-compose logs -f backend
```

### Opción 2: Ejecución local (desarrollo)

#### 1. Base de datos PostgreSQL

```bash
# Si tienes Docker solo para la DB:
docker run -d \
  --name pipidepulus-db \
  -e POSTGRES_USER=pipidepulus \
  -e POSTGRES_PASSWORD=pipidepulus \
  -e POSTGRES_DB=pipidepulus_db \
  -p 5432:5432 \
  postgres:16-alpine

# O usando docker-compose solo para la DB:
docker-compose up -d db
```

#### 2. Backend (FastAPI)

```bash
cd backend

# Crear entorno virtual
python -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar migraciones
alembic upgrade head

# Arrancar servidor de desarrollo
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 3. Frontend (Next.js 16)

```bash
cd frontend

# Instalar dependencias
npm install

# Arrancar servidor de desarrollo
npm run dev
```

### Verificar que funciona

```bash
# Health check del backend
curl http://localhost:8000/api/health

# El frontend estará en
# http://localhost:3000
```

### Variables de entorno requeridas (.env)

```env
OPENAI_API_KEY=sk-...                           # Tu API key de OpenAI
OPENAI_VECTOR_STORE_ID=vs_...                   # Vector Store de Metodología Propulsa
OPENAI_PROJECTS_VECTOR_STORE_ID=vs_...          # Vector Store de Proyectos
DATABASE_URL=postgresql://pipidepulus:pipidepulus@localhost:5432/pipidepulus_db
DEBUG=false
CORS_ORIGINS=["http://localhost:3000"]
```

---

## Configuración del Entorno Local (WSL)

En entornos WSL 2 sin integración Docker Desktop, la aplicación se ejecuta completamente en local. A continuación se documenta el procedimiento verificado.

### Prerequisitos verificados

| Componente | Versión | Comando |
|------------|---------|--------|
| Python | 3.12.3 | `python3 --version` |
| Node.js | 22.21.0 | `node --version` |
| npm | 11.11.0 | `npm --version` |
| PostgreSQL | 16 (local) | `pg_isready -h localhost -p 5432` |
| uvicorn | (venv) | `backend/.venv/bin/uvicorn` |
| alembic | (venv) | `backend/.venv/bin/alembic` |

### Paso 1: Crear usuario y base de datos PostgreSQL

```bash
# Usar autenticación peer (sudo) ya que la contraseña del usuario postgres puede no estar configurada
sudo -u postgres psql -c "CREATE USER pipidepulus WITH PASSWORD 'pipidepulus';"
sudo -u postgres psql -c "CREATE DATABASE pipidepulus_db OWNER pipidepulus;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE pipidepulus_db TO pipidepulus;"
```

**Verificar conexión:**

```bash
PGPASSWORD=pipidepulus psql -h localhost -U pipidepulus -d pipidepulus_db -c "SELECT current_user, current_database();"
# Resultado esperado:
#  current_user | current_database
# --------------+------------------
#  pipidepulus  | pipidepulus_db
```

### Paso 2: Ejecutar migraciones

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
```

**Tablas creadas (8):**

```
alembic_version | call_specs | conversations | generated_docs | messages | projects | uploaded_documents | users
```

### Paso 3: Arrancar el backend

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Verificar:**

```bash
curl -s http://localhost:8000/api/health
# {"status":"healthy","app":"Pipidepulus AI"}
```

### Paso 4: Arrancar el frontend

```bash
cd frontend
npm install
npm run dev
```

**Verificar:**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000
# 200
```

### Smoke Tests del API

```bash
# Crear usuario
curl -s -X POST http://localhost:8000/api/users/ \
  -H 'Content-Type: application/json' \
  -d '{"name":"Test User","email":"test@example.com"}'

# Listar proyectos
curl -s http://localhost:8000/api/projects/

# Listar convocatorias
curl -s http://localhost:8000/api/calls/
```

> **Nota:** Las rutas del API usan trailing slash (`/api/users/`, `/api/projects/`). Si usas `curl` sin el `/` final, recibirás un redirect 307. Agrega `-L` para seguir redirects o incluye el `/` al final.

### Diagrama del entorno local

```mermaid
graph LR
    subgraph "WSL 2 (Ubuntu)"
        PG[("PostgreSQL 16<br/>:5432")]
        BE["FastAPI + Uvicorn<br/>:8000"]
        FE["Next.js 16 Dev<br/>:3000"]
    end

    subgraph "Servicios Externos"
        OAI["OpenAI API<br/>gpt-5-mini"]
        VS1["Vector Store<br/>Metodología"]
        VS2["Vector Store<br/>Proyectos"]
    end

    FE -->|API calls| BE
    BE -->|SQLAlchemy| PG
    BE -->|Responses API| OAI
    BE -->|file_search| VS1
    BE -->|file_search<br/>+ uploads| VS2
```
