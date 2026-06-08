"""
Hybrid Vector Store service: ChromaDB (static KB) + pgvector (dynamic project docs).

Instrumented with Prometheus metrics via app.observability.
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import chromadb
import ollama
from sqlalchemy import text
from sqlalchemy.orm import Session
from pgvector.sqlalchemy import Vector as PGVector
from app.config import get_settings

if TYPE_CHECKING:
    from app.models.document import DocumentEmbedding

VECTOR_DIM = 768
logger = logging.getLogger(__name__)

# ── Observability helpers (lazy to avoid hard-dep on prometheus_client at startup) ──

def _obs():
    """Return custom metrics dict if available, else None."""
    try:
        from app.main import _has_metrics, _observability_metrics
        if _has_metrics:
            return _observability_metrics
    except Exception:
        pass
    return None


def _record_ollama_embedding(metrics: dict, elapsed_s: float) -> None:
    """Record embedding attempt with latency."""
    if not metrics:
        return
    m = metrics.get("ollama_embedding_duration")
    if m is not None:
        m.labels(model=get_settings().OLLAMA_EMBEDDING_MODEL).observe(elapsed_s)
    att = metrics.get("ollama_embedding_attempts")
    if att is not None:
        att.inc(1)


def _record_ollama_embedding_error(metrics: dict) -> None:
    if not metrics:
        return
    err = metrics.get("ollama_embedding_error")
    if err is not None:
        err.inc(1)


def _record_vector_query(metrics: dict, store: str, elapsed_s: float, success: bool = True) -> None:
    if not metrics:
        return
    cnt = metrics.get("vectorstore_query")
    if cnt is not None:
        cnt.labels(store=store).inc(1)
    hist = metrics.get("vectorstore_query_duration")
    if hist is not None and success and elapsed_s > 0:
        hist.labels(store=store).observe(elapsed_s)


def _record_vector_upload(metrics: dict, store: str, elapsed_s: float, success: bool = True) -> None:
    if not metrics:
        return
    cnt = metrics.get("vectorstore_upload")
    if cnt is not None:
        status = "success" if success else "error"
        cnt.labels(store=store, status=status).inc(1)
        if not success:
            err = metrics.get("vectorstore_upload_error")
            if err is not None:
                err.labels(store=store).inc(1)
    hist = metrics.get("vectorstore_upload_duration")
    if hist is not None and success and elapsed_s > 0:
        hist.labels(store=store).observe(elapsed_s)


# ──────────────── Shared: Ollama Embedding Function ────────────────

class OllamaEmbeddingFn:
    """Custom embedding function wrapping Ollama's /api/embed endpoint."""
    def __init__(self, model: str | None = None):
        self.model = model or get_settings().OLLAMA_EMBEDDING_MODEL

    def embed(self, text: str) -> list[float]:
        _obs_metrics = _obs()  # capture at call site for timing
        t0 = time.monotonic()
        try:
            resp = ollama.embeddings(model=self.model, prompt=text)
            elapsed = time.monotonic() - t0
            _record_ollama_embedding(_obs_metrics, elapsed)
            emb = resp["embedding"]
            return [0.0 if (v != v or abs(v) == float('inf')) else v for v in emb]
        except Exception:
            _record_ollama_embedding_error(_obs_metrics)
            raise

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def safe_vector(vector: list[float]) -> list[float]:
    """Replace NaN and Inf values with 0.0 for pgvector safety."""
    result = []
    for v in vector:
        if (v != v) or (abs(v) == float('inf')):
            result.append(0.0)
        else:
            result.append(v)
    return result


# ──────────────── ChromaDB Knowledge Base Store ────────────────

_chroma_client = None
_kb_collection = None


def _ensure_kb():
    global _chroma_client, _kb_collection
    if _chroma_client is None:
        settings = get_settings()
        path = settings.CHROMA_DB_PATH
        _chroma_client = chromadb.PersistentClient(path=path)
        embedding_fn = OllamaEmbeddingFn()
        _kb_collection = _chroma_client.get_or_create_collection(
            name="knowledge_base",
            embedding_function=lambda texts: [
                safe_vector(e) for e in embedding_fn.embed_batch(texts)
            ],
            metadata={"hnsw:space": "cosine"},
        )
    return _kb_collection


def search_knowledge_base(query: str, max_results: int = 10) -> list[dict]:
    """Query ChromaDB knowledge base for static methodology content."""
    _obs_metrics = _obs()
    t0 = time.monotonic()
    col = _ensure_kb()
    if col.count() == 0:
        _record_vector_query(_obs_metrics, "chromadb", time.monotonic() - t0, success=False)
        return []
    results = col.query(
        query_texts=[query],
        n_results=max_results,
        include=["documents", "metadatas", "distances"],
    )
    items = []
    for i in range(len(results["ids"][0])):
        items.append({
            "content": results["documents"][0][i],
            "score": results["distances"][0][i],
            "filename": (results["metadatas"][0][i] or {}).get("filename", "unknown"),
        })
    _record_vector_query(_obs_metrics, "chromadb", time.monotonic() - t0, success=True)
    return items


def upload_bytes_to_knowledge_base(file_bytes: bytes, filename: str) -> str:
    """Upload document bytes, chunk, embed, and index into ChromaDB. Returns ChromaDB ID."""
    _obs_metrics = _obs()
    t0 = time.monotonic()
    try:
        col = _ensure_kb()
        texts = _chunk_document(file_bytes, filename)
        now = datetime.now(timezone.utc)
        ids = [str(uuid.uuid4()) for _ in texts]

        metadatas = [
            {"filename": filename[:200], "source": "uploaded", "uploaded_at": str(now)}
            for _ in texts
        ]
        col.add(
            documents=texts,
            ids=ids,
            metadatas=metadatas,
        )
        _record_vector_upload(_obs_metrics, "chromadb", time.monotonic() - t0, success=True)
        return ids[0] if ids else ""
    except Exception:
        _record_vector_upload(_obs_metrics, "chromadb", time.monotonic() - t0, success=False)
        raise


# ──────────────── pgvector Project Documents Store ────────────────

def search_projects_store(project_id: str | uuid.UUID, query: str, max_results: int = 8) -> list[dict]:
    """Search project documents via pgvector with strict WHERE project_id = $1 filtering."""
    from app.database import engine, SessionLocal

    _obs_metrics = _obs()
    t0 = time.monotonic()
    query_vec = safe_vector(OllamaEmbeddingFn().embed(query))
    pid = str(project_id)

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
            "project_id": pid,
            "query_vec": query_vec,
            "max_results": max_results,
        })
        rows = result.fetchall()

    _record_vector_query(_obs_metrics, "pgvector", time.monotonic() - t0, success=True)

    items = []
    for row in rows:
        items.append({
            "content": row[0],
            "metadata": row[1],
            "score": row[2] if row[2] is not None else None,
            "filename": (row[1] or {}).get("filename", "unknown"),
        })
    return items


def upload_bytes_to_projects_store(file_bytes: bytes, filename: str, project_id: str) -> str:
    """Upload document, chunk, embed, and INSERT into pgvector with WHERE project_id isolation."""
    from app.database import engine, SessionLocal

    _obs_metrics = _obs()
    t0 = time.monotonic()
    try:
        texts = _chunk_document(file_bytes, filename)
        embeddings_all = [safe_vector(OllamaEmbeddingFn().embed(t)) for t in texts]

        now = datetime.now(timezone.utc)
        project_uuid = str(uuid.UUID(project_id))

        with SessionLocal() as db:
            from app.models.document import DocumentEmbedding
            rows = []
            for i, (text, emb) in enumerate(zip(texts, embeddings_all)):
                rows.append({
                    "project_id": project_uuid,
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

            if rows:
                db.bulk_insert_mappings(DocumentEmbedding, rows)
                db.commit()

        # Mark pending uploaded_documents as indexed for this project
        with SessionLocal() as db:
            from app.models.document import UploadedDocument
            uploaders = (
                db.query(UploadedDocument)
                .filter(UploadedDocument.project_id == project_uuid, UploadedDocument.indexing_status == "pending")
                .all()
            )
            for ud in uploaders:
                ud.indexing_status = "indexed"
            if uploaders:
                db.commit()

        _record_vector_upload(_obs_metrics, "pgvector", time.monotonic() - t0, success=True)
        return project_uuid
    except Exception:
        _record_vector_upload(_obs_metrics, "pgvector", time.monotonic() - t0, success=False)
        raise


# ──────────────── Chunking (shared) ────────────────

def _chunk_document(file_bytes: bytes, filename: str) -> list[str]:
    """Split document into chunks. Simple text split."""
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1", errors="replace")

    if len(text) <= 800:
        return [text]

    chunks = []
    chunk_size = 800
    overlap = 200
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap

    return chunks
