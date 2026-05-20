import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.call_spec import CallSpec
from app.schemas.call_spec import CallSpecCreate, CallSpecResponse
from app.services.vector_store import upload_bytes_to_projects_store

router = APIRouter(prefix="/calls", tags=["call_specs"])


@router.post("", response_model=CallSpecResponse, status_code=201)
def create_call_spec(data: CallSpecCreate, db: Session = Depends(get_db)):
    call_spec = CallSpec(**data.model_dump())
    db.add(call_spec)
    db.commit()
    db.refresh(call_spec)
    return call_spec


@router.get("", response_model=list[CallSpecResponse])
def list_call_specs(db: Session = Depends(get_db)):
    return db.query(CallSpec).order_by(CallSpec.created_at.desc()).all()


@router.get("/{call_spec_id}", response_model=CallSpecResponse)
def get_call_spec(call_spec_id: uuid.UUID, db: Session = Depends(get_db)):
    call_spec = db.query(CallSpec).filter(CallSpec.id == call_spec_id).first()
    if not call_spec:
        raise HTTPException(status_code=404, detail="Call spec not found")
    return call_spec


@router.post("/{call_spec_id}/upload")
async def upload_call_document(
    call_spec_id: uuid.UUID,
    file: UploadFile = File(...),
    project_id: str | None = None,
    db: Session = Depends(get_db),
):
    """Upload a call document (PDF/DOCX) to the projects vector store.

    Pass ``project_id`` as a query parameter to tag the file so that per-project
    file_search filters can find it.  Without a project_id the document is stored
    untagged and will only surface in unfiltered (no active project) searches.
    """
    call_spec = db.query(CallSpec).filter(CallSpec.id == call_spec_id).first()
    if not call_spec:
        raise HTTPException(status_code=404, detail="Call spec not found")

    content = await file.read()
    file_id = upload_bytes_to_projects_store(
        content, file.filename or "document", project_id=project_id
    )

    return {
        "status": "uploaded",
        "file_id": file_id,
        "filename": file.filename,
        "call_spec_id": str(call_spec_id),
        "project_id": project_id,
    }
