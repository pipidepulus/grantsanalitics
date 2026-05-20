"""
Vector Store service for managing OpenAI Vector Stores.
- VS_Knowledge_Base: Static methodology (Propulsa)
- VS_Project_Memory: Dynamic project & call document storage
"""

import logging
import time

from openai import OpenAI
from app.config import get_settings

settings = get_settings()
client = OpenAI(api_key=settings.OPENAI_API_KEY)


def search_knowledge_base(query: str, max_results: int = 10) -> list[dict]:
    """Search the static knowledge base (Metodología Propulsa) vector store."""
    response = client.vector_stores.search(
        vector_store_id=settings.OPENAI_VECTOR_STORE_ID,
        query=query,
        max_num_results=max_results,
    )
    results = []
    for item in response.data:
        results.append({
            "content": item.content[0].text if item.content else "",
            "score": item.score,
            "filename": item.filename,
        })
    return results


def search_projects_store(query: str, max_results: int = 10) -> list[dict]:
    """Search the dynamic projects & call documents vector store."""
    response = client.vector_stores.search(
        vector_store_id=settings.OPENAI_PROJECTS_VECTOR_STORE_ID,
        query=query,
        max_num_results=max_results,
    )
    results = []
    for item in response.data:
        results.append({
            "content": item.content[0].text if item.content else "",
            "score": item.score,
            "filename": item.filename,
        })
    return results


def upload_to_projects_store(file_path: str, filename: str) -> str:
    """Upload a file to the projects vector store and return the file ID."""
    with open(file_path, "rb") as f:
        uploaded_file = client.files.create(file=f, purpose="assistants")

    client.vector_stores.files.create(
        vector_store_id=settings.OPENAI_PROJECTS_VECTOR_STORE_ID,
        file_id=uploaded_file.id,
    )
    return uploaded_file.id


def upload_bytes_to_projects_store(file_bytes: bytes, filename: str, project_id: str | None = None) -> str:
    """Upload file bytes to the projects vector store.

    Tags the file with ``project_id`` as a vector-store attribute so the
    retrieval agent can filter by project and avoid cross-project contamination.

    If a file with the same name and project_id already exists in the vector
    store, it is deleted first to prevent duplicates.

    Polls until the vector-store file reaches ``completed`` status (or the
    120-second timeout expires) so callers can be sure the file is searchable
    before returning.
    """
    logger = logging.getLogger(__name__)

    # Deduplicate: remove any existing VS files with the same name + project_id
    if project_id:
        try:
            existing = client.vector_stores.files.list(
                vector_store_id=settings.OPENAI_PROJECTS_VECTOR_STORE_ID,
                limit=100,
            )
            for vs_file in existing.data:
                attrs = getattr(vs_file, "attributes", {}) or {}
                if attrs.get("project_id") != project_id:
                    continue
                try:
                    file_obj = client.files.retrieve(vs_file.id)
                    if file_obj.filename == filename:
                        client.vector_stores.files.delete(
                            vector_store_id=settings.OPENAI_PROJECTS_VECTOR_STORE_ID,
                            file_id=vs_file.id,
                        )
                        client.files.delete(vs_file.id)
                        logger.info(
                            "vector_store_duplicate_removed",
                            extra={"file_id": vs_file.id, "filename": filename},
                        )
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("dedup_check_failed", extra={"error": str(exc)})

    uploaded_file = client.files.create(
        file=(filename, file_bytes),
        purpose="assistants",
    )
    vs_file_kwargs: dict = {
        "vector_store_id": settings.OPENAI_PROJECTS_VECTOR_STORE_ID,
        "file_id": uploaded_file.id,
    }
    if project_id:
        vs_file_kwargs["attributes"] = {"project_id": str(project_id)}
    vs_file = client.vector_stores.files.create(**vs_file_kwargs)

    # Poll until OpenAI finishes indexing so file_search can find the document.
    max_wait_seconds = 120
    poll_interval = 3
    elapsed = 0
    while vs_file.status == "in_progress" and elapsed < max_wait_seconds:
        time.sleep(poll_interval)
        elapsed += poll_interval
        vs_file = client.vector_stores.files.retrieve(
            vector_store_id=settings.OPENAI_PROJECTS_VECTOR_STORE_ID,
            file_id=uploaded_file.id,
        )

    if vs_file.status != "completed":
        logger.warning(
            "vector_store_file_not_completed",
            extra={
                "file_id": uploaded_file.id,
                "filename": filename,
                "status": vs_file.status,
                "elapsed_s": elapsed,
            },
        )
    else:
        logger.info(
            "vector_store_file_indexed",
            extra={"file_id": uploaded_file.id, "filename": filename, "elapsed_s": elapsed},
        )

    return uploaded_file.id
