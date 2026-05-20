"""
Object storage abstraction.

Supports two backends controlled by the ``STORAGE_BACKEND`` env var:

- ``local`` (default) — stores files under ``STORAGE_LOCAL_PATH`` on disk.
  Suitable for development and single-node deployments.
- ``s3`` — stores files in an S3-compatible bucket (AWS S3, MinIO, Cloudflare
  R2, etc.) using ``boto3``.  Requires ``STORAGE_S3_BUCKET``, ``AWS_ACCESS_KEY_ID``
  and ``AWS_SECRET_ACCESS_KEY`` in the environment.

Both backends expose the same three-method interface so callers never need to
know which backend is active.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ──────────────────────────────────────────────
# Abstract interface
# ──────────────────────────────────────────────

class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Persist *data* under *key*; returns the storage key."""

    @abstractmethod
    def load(self, key: str) -> bytes:
        """Retrieve the bytes stored under *key*."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove the object identified by *key* (no-op if absent)."""


# ──────────────────────────────────────────────
# Local filesystem backend
# ──────────────────────────────────────────────

class LocalStorageBackend(StorageBackend):
    """Store files under a local directory.

    Files are written to ``{base_dir}/{key}`` where *key* is the path relative
    to the storage root.  Parent directories are created automatically.
    """

    def __init__(self, base_dir: str | Path = "/var/pipidepulus/storage") -> None:
        self._root = Path(base_dir)
        self._root.mkdir(parents=True, exist_ok=True)
        logger.info("local_storage_init", extra={"root": str(self._root)})

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        dest = self._root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        logger.info("storage_save", extra={"key": key, "bytes": len(data)})
        return key

    def load(self, key: str) -> bytes:
        src = self._root / key
        if not src.exists():
            raise FileNotFoundError(f"Storage key not found: {key}")
        return src.read_bytes()

    def delete(self, key: str) -> None:
        target = self._root / key
        if target.exists():
            target.unlink()
            logger.info("storage_delete", extra={"key": key})


# ──────────────────────────────────────────────
# S3 backend (requires boto3 to be installed)
# ──────────────────────────────────────────────

class S3StorageBackend(StorageBackend):
    """Store files in an S3-compatible bucket via boto3."""

    def __init__(self, bucket: str, endpoint_url: str | None = None) -> None:
        try:
            import boto3  # noqa: F401 — optional dependency
            self._boto3 = boto3
        except ImportError as exc:
            raise RuntimeError(
                "boto3 is required for S3 storage. Install it with: pip install boto3"
            ) from exc
        self._bucket = bucket
        self._endpoint = endpoint_url
        self._client = self._boto3.client("s3", endpoint_url=endpoint_url)
        logger.info("s3_storage_init", extra={"bucket": bucket})

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        logger.info("storage_save", extra={"backend": "s3", "key": key, "bytes": len(data)})
        return key

    def load(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)
        logger.info("storage_delete", extra={"backend": "s3", "key": key})


# ──────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────

_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the configured storage backend (singleton, created on first call)."""
    global _backend
    if _backend is not None:
        return _backend

    backend_type = getattr(settings, "STORAGE_BACKEND", "local")

    if backend_type == "s3":
        bucket = getattr(settings, "STORAGE_S3_BUCKET", "")
        endpoint = getattr(settings, "STORAGE_S3_ENDPOINT_URL", None)
        if not bucket:
            raise RuntimeError("STORAGE_S3_BUCKET must be set when STORAGE_BACKEND=s3")
        _backend = S3StorageBackend(bucket=bucket, endpoint_url=endpoint or None)
    else:
        local_path = getattr(settings, "STORAGE_LOCAL_PATH", "/var/pipidepulus/storage")
        _backend = LocalStorageBackend(base_dir=local_path)

    return _backend


# ──────────────────────────────────────────────
# Key helpers
# ──────────────────────────────────────────────

def make_document_key(project_id: str, filename: str) -> str:
    """Generate a deterministic, collision-safe storage key for an uploaded document."""
    unique = uuid.uuid4().hex[:8]
    safe_name = filename.replace(" ", "_")
    return f"projects/{project_id}/uploads/{unique}_{safe_name}"


def make_generated_doc_key(project_id: str, filename: str) -> str:
    """Generate a storage key for a generated Word document."""
    unique = uuid.uuid4().hex[:8]
    return f"projects/{project_id}/generated/{unique}_{filename}"
