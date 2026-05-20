"""
Vector store retrieval configuration.

Responsible for building the ``file_search`` tool entries for the Responses API
and enforcing per-project isolation:

- ``OPENAI_VECTOR_STORE_ID``  — static knowledge base (Propulsa methodology).
  Always searched unfiltered regardless of active project.
- ``OPENAI_PROJECTS_VECTOR_STORE_ID`` — dynamic project documents.
  The Responses API ``file_search`` filter is unreliable, so project documents
  are retrieved manually via ``retrieve_project_context`` and injected into the
  prompt as ``<project_documents>`` context before the API call.

Keeping this logic in its own module makes the isolation policy explicit,
testable, and decoupled from the conversation orchestrator.
"""

import logging
import uuid

from openai import OpenAI
from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def build_file_search_tools(project_id: uuid.UUID | None) -> list[dict]:
    """Return ``file_search`` entries for an OpenAI Responses API call.

    When a project is active, only the static KB is included here.
    Project-specific documents are injected separately via
    ``retrieve_project_context`` to avoid reliance on the Responses API
    filter which does not reliably honour vector-store file attributes.
    """
    if project_id:
        # Project docs are pre-retrieved and injected as <project_documents> context.
        # Only the KB file_search is needed for methodology questions.
        return [
            {
                "type": "file_search",
                "vector_store_ids": [settings.OPENAI_VECTOR_STORE_ID],
            },
        ]

    # No active project — search both stores without restrictions
    return [
        {
            "type": "file_search",
            "vector_store_ids": [
                settings.OPENAI_VECTOR_STORE_ID,
                settings.OPENAI_PROJECTS_VECTOR_STORE_ID,
            ],
        }
    ]


def retrieve_project_context(project_id: uuid.UUID, query: str, max_results: int = 8) -> str:
    """Retrieve relevant project documents via a direct filtered vector store search.

    Uses the synchronous OpenAI client so it can be called from a threadpool
    (via ``asyncio.to_thread``).  Returns a formatted ``<project_documents>``
    block ready to be injected into the prompt, or an empty string when there
    are no matches.
    """
    sync_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        result = sync_client.vector_stores.search(
            vector_store_id=settings.OPENAI_PROJECTS_VECTOR_STORE_ID,
            query=query,
            filters={
                "type": "eq",
                "key": "project_id",
                "value": str(project_id),
            },
            max_num_results=max_results,
        )
        if not result.data:
            return ""
        chunks: list[str] = []
        for item in result.data:
            content = item.content[0].text if item.content else ""
            if content.strip():
                chunks.append(f"[Archivo: {item.filename}]\n{content}")
        if not chunks:
            return ""
        joined = "\n\n---\n\n".join(chunks)
        return f"<project_documents>\n{joined}\n</project_documents>"
    except Exception as exc:
        logger.warning("retrieve_project_context_failed", extra={"project_id": str(project_id), "error": str(exc)})
        return ""
