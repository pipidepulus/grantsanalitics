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
        "function": {
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
        },
    })

    # pgvector project tool (only when project context is active)
    if project_id:
        tools.append({
            "type": "function",
            "function": {
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
            },
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
