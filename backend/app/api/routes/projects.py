import uuid
from datetime import datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project
from app.models.cyrano_evaluation import CyranoEvaluation
from app.models.rag_event import RagEvent
from app.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectResponse, ProjectListResponse,
    CyranoEvaluationResponse,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(**data.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectListResponse])
def list_projects(
    user_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    projects = (
        db.query(Project)
        .filter(Project.user_id == user_id)
        .order_by(Project.updated_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return projects


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: uuid.UUID, data: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: uuid.UUID, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # Delete related documents first (FK constraints)
    from app.models.document import GeneratedDoc, UploadedDocument
    from app.models.conversation import Conversation
    db.query(GeneratedDoc).filter(GeneratedDoc.project_id == project_id).delete()
    db.query(UploadedDocument).filter(UploadedDocument.project_id == project_id).delete()
    # Unlink conversations (don't delete them, just remove the project reference)
    db.query(Conversation).filter(Conversation.project_id == project_id).update({"project_id": None})
    db.delete(project)
    db.commit()


class GenerateDocRequest(BaseModel):
    language: str = "es"


@router.post("/{project_id}/generate-document")
def generate_project_document(project_id: uuid.UUID, data: GenerateDocRequest, db: Session = Depends(get_db)):
    """Generate a professional Word document from the project's methodology sections only."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    lang = data.language

    # Always build from individual methodology sections — clean, structured content
    # Pull text from structured fields or json_data as fallback
    jd = project.json_data or {}

    def _get(field_obj, jd_key):
        if field_obj:
            if isinstance(field_obj, dict) and "text" in field_obj:
                return field_obj["text"]
            if isinstance(field_obj, str):
                return field_obj
        if jd.get(jd_key):
            return jd[jd_key]
        return None

    problem = project.problem_definition or jd.get("problem_definition")
    objectives = _get(project.objectives_tree, "objectives")
    methodology = _get(project.value_chain, "methodology")
    timeline = _get(project.timeline, "timeline")
    budget = _get(project.budget, "budget")

    section_titles = {
        "es": ["1. Identificación del Problema", "2. Árbol de Problemas / Objetivos", "3. Cadena de Valor / Metodología", "4. Cronograma", "5. Presupuesto"],
        "en": ["1. Problem Identification", "2. Problem Tree / Objectives", "3. Value Chain / Methodology", "4. Timeline", "5. Budget"],
    }
    titles = section_titles.get(lang, section_titles["es"])

    sections = []
    for title_label, content in zip(titles, [problem, objectives, methodology, timeline, budget]):
        if content:
            sections.append(f"# {title_label}\n\n{content}")

    if not sections:
        raise HTTPException(
            status_code=400,
            detail="El proyecto no tiene contenido de la metodología. Usa el chat para desarrollar las secciones primero.",
        )

    # Build markdown with project title header
    doc_content = f"# {project.title}\n\n" + "\n\n---\n\n".join(sections)

    from app.services.tools import handle_generate_word_document
    import json

    result = json.loads(handle_generate_word_document({
        "project_id": str(project_id),
        "language": lang,
        "content": doc_content,
    }, db))

    if result.get("status") == "blocked":
        raise HTTPException(status_code=400, detail=result["message"])

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result["message"])

    return {
        "status": "success",
        "document_id": result["document_id"],
        "filename": result["filename"],
        "download_url": result["download_url"],
        "message": f"Documento '{result['filename']}' generado exitosamente.",
    }


@router.get(
    "/{project_id}/evaluations",
    response_model=list[CyranoEvaluationResponse],
    summary="Historial de evaluaciones Cyrano",
)
def list_cyrano_evaluations(project_id: uuid.UUID, db: Session = Depends(get_db)):
    """Return all Cyrano diagnostic evaluations for a project, ordered newest first.

    Each record contains the score, per-section breakdown, structured feedback
    (gaps + recommendations), verdict, and the sequential version number so
    clients can display score progression over time.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    evaluations = (
        db.query(CyranoEvaluation)
        .filter(CyranoEvaluation.project_id == project_id)
        .order_by(CyranoEvaluation.version.desc())
        .all()
    )
    return evaluations


class RagEventResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    project_id: uuid.UUID | None
    query: str
    tools_used: list[str] | None
    has_file_search: bool
    has_web_search: bool
    function_tool_count: int
    response_latency_ms: int | None
    turn_index: int
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get(
    "/{project_id}/rag-events",
    response_model=list[RagEventResponse],
    summary="Historial de eventos RAG (grounding audit)",
)
def list_rag_events(
    project_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Return recent RAG events for a project (newest first, max 200).

    Each record represents one completed AI turn: what retrieval tools were
    invoked, whether file_search grounding was active, and the total latency.
    Use this data to evaluate retrieval quality and detect hallucination risk.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    events = (
        db.query(RagEvent)
        .filter(RagEvent.project_id == project_id)
        .order_by(RagEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return events
