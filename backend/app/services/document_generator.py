"""
Document generation service for creating Word documents from project data.
"""

from io import BytesIO
from sqlalchemy.orm import Session
from app.models.project import Project
from app.models.document import GeneratedDoc


def get_document_bytes(db: Session, document_id: str) -> tuple[bytes, str] | None:
    """Get document binary and filename by ID."""
    doc = db.query(GeneratedDoc).filter(GeneratedDoc.id == document_id).first()
    if not doc:
        return None
    return doc.binary_file, doc.filename
