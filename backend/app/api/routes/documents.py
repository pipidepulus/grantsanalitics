import logging
import uuid
from urllib.parse import quote
from io import BytesIO
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models.document import GeneratedDoc, UploadedDocument
from app.schemas.document import GeneratedDocResponse, UploadedDocumentResponse
from app.services.storage import get_storage, make_document_key
from app.services.vector_store import upload_bytes_to_projects_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_limiter = Limiter(key_func=get_remote_address)

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "text/markdown",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "image/png",
    "image/jpeg",
}

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _index_and_store_background(
    doc_id: uuid.UUID,
    file_bytes: bytes,
    filename: str,
    project_id: uuid.UUID,
    content_type: str,
) -> None:
    """Background task: persist bytes to object storage and index in vector store.

    Runs after the HTTP response has already been returned to the client.
    Updates ``storage_path`` and ``indexing_status`` on the document row.
    """
    db = SessionLocal()
    try:
        doc = db.query(UploadedDocument).filter(UploadedDocument.id == doc_id).first()
        if doc is None:
            return

        # Step 1 — persist to object storage
        storage_errors = []
        try:
            storage = get_storage()
            key = make_document_key(str(project_id), filename)
            storage.save(key, file_bytes, content_type)
            doc.storage_path = key
            # Free the inline binary once it's safely in object storage
            doc.binary_file = None
        except Exception as exc:
            storage_errors.append(str(exc))
            logger.error("storage_save_failed", extra={"doc_id": str(doc_id), "error": str(exc)})

        # Step 2 — index in vector store
        try:
            vector_file_id = upload_bytes_to_projects_store(
                file_bytes, filename, project_id=str(project_id)
            )
            doc.vector_store_file_id = vector_file_id
            doc.indexing_status = "indexed"
            logger.info("document_indexed", extra={"doc_id": str(doc_id), "vector_file_id": vector_file_id})
        except Exception as exc:
            doc.indexing_status = "failed"
            logger.error("document_indexing_failed", extra={"doc_id": str(doc_id), "error": str(exc)})

        db.commit()
    finally:
        db.close()


@router.post("/upload", response_model=UploadedDocumentResponse, status_code=202)
@_limiter.limit("10/minute")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    project_id: str = Form(...),
    user_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a document to a project.

    Persists the document record immediately (202 Accepted) then runs storage
    + vector-store indexing as a background task.  Poll
    ``GET /documents/project/{project_id}/all`` to watch ``indexing_status``
    transition from ``"pending"`` → ``"indexed"`` or ``"failed"``.
    """
    try:
        project_uuid = uuid.UUID(project_id)
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="project_id y user_id deben ser UUIDs válidos.")

    content_type = file.content_type
    if not content_type or content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no permitido: {content_type or 'desconocido'}. Acepta: PDF, DOCX, DOC, TXT, MD, XLSX, PNG, JPEG",
        )

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="El archivo excede el tamaño máximo de 20 MB")

    original_filename = (file.filename or "document")[:255]
    safe_filename = original_filename.replace(" ", "_")

    # Persist record immediately; binary is held in memory only until
    # the background task writes it to object storage, then cleared.
    uploaded_doc = UploadedDocument(
        project_id=project_uuid,
        user_id=user_uuid,
        filename=safe_filename,
        original_filename=original_filename,
        file_size=len(file_bytes),
        content_type=content_type,
        binary_file=file_bytes,  # Cleared by background task after storage write
        indexing_status="pending",
    )
    db.add(uploaded_doc)
    db.commit()
    db.refresh(uploaded_doc)

    background_tasks.add_task(
        _index_and_store_background,
        uploaded_doc.id,
        file_bytes,
        safe_filename,
        project_uuid,
        content_type,
    )

    return uploaded_doc


@router.get("/project/{project_id}/all")
def list_all_project_documents(
    project_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List all documents for a project: both uploaded and generated."""
    uploaded = (
        db.query(UploadedDocument)
        .filter(UploadedDocument.project_id == project_id)
        .order_by(UploadedDocument.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    generated = (
        db.query(GeneratedDoc)
        .filter(GeneratedDoc.project_id == project_id)
        .order_by(GeneratedDoc.version_number.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "uploaded": [
            {
                "id": str(d.id),
                "filename": d.original_filename,
                "file_size": d.file_size,
                "content_type": d.content_type,
                "type": "uploaded",
                "indexing_status": d.indexing_status,
                "created_at": d.created_at.isoformat(),
            }
            for d in uploaded
        ],
        "generated": [
            {
                "id": str(d.id),
                "filename": d.filename,
                "version_number": d.version_number,
                "type": "generated",
                "created_at": d.created_at.isoformat(),
            }
            for d in generated
        ],
    }


@router.get("/project/{project_id}", response_model=list[GeneratedDocResponse])
def list_project_documents(project_id: uuid.UUID, db: Session = Depends(get_db)):
    docs = (
        db.query(GeneratedDoc)
        .filter(GeneratedDoc.project_id == project_id)
        .order_by(GeneratedDoc.version_number.desc())
        .all()
    )
    return docs


@router.post("/{document_id}/retry-indexing")
def retry_document_indexing(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Re-queue indexing for a document stuck in 'failed' or 'pending' state."""
    doc = db.query(UploadedDocument).filter(UploadedDocument.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.indexing_status == "indexed":
        return {"status": "already_indexed", "document_id": str(document_id)}

    # Load file bytes from storage if inline copy was already cleared
    if doc.binary_file:
        file_bytes = doc.binary_file
    elif doc.storage_path:
        try:
            file_bytes = get_storage().load(doc.storage_path)
        except FileNotFoundError:
            raise HTTPException(
                status_code=409,
                detail="File bytes not available in storage; cannot retry indexing.",
            )
    else:
        raise HTTPException(
            status_code=409,
            detail="No file bytes available; cannot retry indexing.",
        )

    doc.indexing_status = "pending"
    db.commit()

    background_tasks.add_task(
        _index_and_store_background,
        doc.id,
        file_bytes,
        doc.filename,
        doc.project_id,
        doc.content_type,
    )
    return {"status": "retry_queued", "document_id": str(document_id)}


@router.delete("/{document_id}")
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a document (uploaded or generated)."""
    doc = db.query(GeneratedDoc).filter(GeneratedDoc.id == document_id).first()
    if doc:
        db.delete(doc)
        db.commit()
        return {"ok": True}

    uploaded = db.query(UploadedDocument).filter(UploadedDocument.id == document_id).first()
    if uploaded:
        db.delete(uploaded)
        db.commit()
        return {"ok": True}

    raise HTTPException(status_code=404, detail="Document not found")


def _content_disposition(filename: str) -> str:
    """Build a Content-Disposition header safe for non-ASCII filenames."""
    ascii_name = filename.encode("ascii", "replace").decode("ascii")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/{document_id}/download")
def download_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = db.query(GeneratedDoc).filter(GeneratedDoc.id == document_id).first()
    if doc:
        if doc.storage_path:
            try:
                data = get_storage().load(doc.storage_path)
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail="Storage object not found")
        elif doc.binary_file:
            data = doc.binary_file
        else:
            raise HTTPException(status_code=404, detail="Document has no stored content")
        return StreamingResponse(
            BytesIO(data),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": _content_disposition(doc.filename)},
        )

    uploaded = db.query(UploadedDocument).filter(UploadedDocument.id == document_id).first()
    if not uploaded:
        raise HTTPException(status_code=404, detail="Document not found")

    if uploaded.storage_path:
        try:
            data = get_storage().load(uploaded.storage_path)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Storage object not found")
    elif uploaded.binary_file:
        data = uploaded.binary_file
    else:
        raise HTTPException(status_code=404, detail="Document has no stored content")

    return StreamingResponse(
        BytesIO(data),
        media_type=uploaded.content_type,
        headers={"Content-Disposition": _content_disposition(uploaded.original_filename)},
    )
