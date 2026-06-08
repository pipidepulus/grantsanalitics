# Text Generation Specification

## Purpose

Definir los requisitos del nuevo motor de generación de texto local usando `qwen2.5-coder:14b-16k` vía Ollama API, reemplazando OpenAI Responses API (gpt-5-mini). Este spec se enfoca exclusivamente en la capa de inferencia; el almacenamiento vectorial se describe en `specs/vector-hybrid/spec.md`.

## ADDED Requirements

### Requirement: Local text generation via Ollama

El sistema DEBE generar respuestas de texto usando `qwen2.5-coder:14b-16k` vía la Ollama API en `http://localhost:11434` en lugar de OpenAI Responses API (`gpt-5-mini`).

#### Scenario: Generación simple de respuesta

- DADO que Ollama está corriendo en `http://localhost:11434`
- Y `OLLAMA_MODEL=qwen2.5-coder:14b` está configurado
- CUANDO un usuario envía un mensaje de chat
- ENTONCES el sistema envía un POST a `/v1/chat/completions` con el modelo configurado
- Y la respuesta ES parseada y retornada al usuario

#### Scenario: Generación con contexto de proyecto

- DADO que un usuario interactúa con un proyecto activo
- Y el prompt incluye `<project_documents>` inyectados por `retrieve_project_context`
- ENTONCES el mensaje del usuario ENVIADO a `/v1/chat/completions` INCLUYE el contexto de proyecto
- Y la respuesta generada ES referenciada al documento del proyecto

### Requirement: Ollama streaming support

El sistema DEBE soportar streaming de respuesta desde Ollama para respuestas largas.

#### Scenario: Streaming de respuesta

- DADO que el usuario solicita una respuesta larga
- CUANDO el sistema llama `ollama.chat()` con `stream=true`
- ENTONCES los tokens SON entregados en chunks al frontend
- Y el frontend PUEDE mostrarlos en tiempo real

### Requirement: Ollama model configuration

El sistema DEBE permitir configurar el modelo de Ollama vía la variable `OLLAMA_MODEL`.

#### Scenario: Modelo personalizado

- DADO que `OLLAMA_MODEL=llama3.1` está configurado
- CUANDO el sistema genera una respuesta
- ENTONCES el modelo `llama3.1` ES usado en la llamada

#### Scenario: Modelo por defecto

- DADO que `OLLAMA_MODEL` no está configurado
- ENTONCES el sistema usa `qwen2.5-coder:14b` por defecto

### Requirement: Automatic Ollama model fallback

El sistema DEBE detectar automáticamente cuando el modelo configurado en `OLLAMA_MODEL` no está disponible en Ollama y alternar sin intervención del usuario.

#### Scenario: Modelo no está descargado en Ollama

- DADO que `OLLAMA_MODEL=qwen2.5-coder:14b` está configurado
- Y el modelo `qwen2.5-coder:14b` no está instalado localmente
- CUANDO se inicia la aplicación o la primera llamada a `/v1/chat/completions`
- ENTONCES se llama `GET /api/tags` para listar modelos disponibles
- Y si no existe `qwen2.5-coder:14b` → se intenta automáticamente `OLLAMA_MODEL_FALLBACK` (`phi3`)
- Y si `phi3` tampoco está → se retorna error informativo: `ollama pull qwen2.5-coder:14b`

#### Scenario: Tool-calling falla con modelo principal

- DADO que `qwen2.5-coder:14b` no soporta tool-calling correctamente
- Y el modelo retorna solo texto sin estructura de `tool_calls`
- CUANDO el sistema detecta la respuesta incorrecta
- ENTONCES reintentar con `OLLAMA_MODEL_FALLBACK` (que debe soportar tool-calling)
- Y si el fallback también falla → continuar sin herramientas para esa petición

#### Scenario: Modelo cae runtime (Ollama offline)

- DADO que Ollama está corriendo al iniciar la app
- Y Ollama cae durante la ejecución
- CUANDO se produce `ConnectionRefusedError` en un POST a `/v1/chat/completions`
- ENTONCES el health check detecta el error
- Y se retorna `{"status": "error", "detail": "Ollama not reachable at ..."}` en `/health`

## REMOVED Requirements

### Requirement: OpenAI Responses API for generation

(Reason: Reemplazado por Ollama `/v1/chat/completions`)

### Requirement: OpenAI asynchronous client for agent

(Reason: Reemplazado por `httpx` o `ollama.AsyncClient` para llamadas locales)

### Requirement: tool_file_search from OpenAI

(Reason: Retrieval ahora se maneja con ChromaDB antes del envío al agente)

## MODIFIED Requirements

### Requirement: Agent conversation orchestration
El sistema DEBE mantener el protocolo de tool-calling en el agente, pero adaptado al formato de Ollama, reemplazando `AsyncOpenAI().responses.create()` con `ollama.chat()` o POST `/v1/chat/completions`.
(Previously: use OpenAI Responses API with tool-calling for conversation orchestration)

#### Scenario: Tool-calling con qwen2.5-coder

- DADO que el prompt incluye `tools` en formato compatible con Ollama
- Y el modelo soporta function calling
- CUANDO el modelo decide invocar una tool
- ENTONCES se retorna un tool message de vuelta al modelo
- Y el modelo genera la respuesta final

#### Scenario: Graceful fallback si tool-calling falla

- DADO que Ollama retorna un error de tool-calling
- CUANDO el sistema intenta invocar una herramienta
- ENTONCES el error ES capturado y se retorna un mensaje de error al usuario
- Sin bloquear el flujo de conversación

### Requirement: Health check for Ollama endpoint

El sistema DEBE verificar conectividad con Ollama en el health check `/health`, devolviendo un campo `"ollama"` con el estatus.
(Previously: check OPENAI_API_KEY and OpenAI endpoint connectivity)

#### Scenario: Ollama health check

- DADO que Ollama está corriendo en `OLLAMA_BASE_URL`
- CUANDO se llama `GET /health`
- ENTONCES el campo `ollama` retorna `{"status": "ok"}`

#### Scenario: Ollama no disponible en health check

- DADO que `OLLAMA_BASE_URL` no es accesible
- CUANDO se llama `/health`
- ENTONCES el campo `ollama` retorna `{"status": "error", "detail": "Ollama not reachable at ..."}`
