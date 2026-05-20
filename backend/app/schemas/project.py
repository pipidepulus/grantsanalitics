import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, field_validator

from app.models.enums import ProjectStatus, ProjectLanguage


class ProjectCreate(BaseModel):
    title: str
    user_id: uuid.UUID
    language: ProjectLanguage = ProjectLanguage.es
    call_spec_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("El título no puede estar vacío.")
        if len(stripped) > 500:
            raise ValueError("El título no puede superar los 500 caracteres.")
        return stripped


class ProjectUpdate(BaseModel):
    title: str | None = None
    status: ProjectStatus | None = None
    language: ProjectLanguage | None = None
    cyrano_score: float | None = None
    json_data: dict | None = None
    problem_definition: str | None = None
    problem_tree: dict | None = None
    objectives_tree: dict | None = None
    value_chain: dict | None = None
    timeline: dict | None = None
    budget: dict | None = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("El título no puede estar vacío.")
        if len(stripped) > 500:
            raise ValueError("El título no puede superar los 500 caracteres.")
        return stripped

    @field_validator("cyrano_score")
    @classmethod
    def score_in_range(cls, v: float | None) -> float | None:
        if v is not None and not (0.0 <= v <= 100.0):
            raise ValueError("cyrano_score debe estar entre 0 y 100.")
        return v

    @field_validator("problem_definition")
    @classmethod
    def problem_definition_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 20_000:
            raise ValueError("problem_definition no puede superar los 20 000 caracteres.")
        return v

    @field_validator("json_data")
    @classmethod
    def json_data_size(cls, v: dict | None) -> dict | None:
        if v is not None:
            import json as _json
            if len(_json.dumps(v)) > 500_000:
                raise ValueError("json_data supera el límite de 500 KB.")
        return v


class ProjectResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    status: str
    cyrano_score: float | None
    language: str
    json_data: dict | None
    problem_definition: str | None
    problem_tree: dict | None
    objectives_tree: dict | None
    value_chain: dict | None
    timeline: dict | None
    budget: dict | None
    call_spec_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    cyrano_score: float | None
    language: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CyranoEvaluationResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    score: float
    sections: dict[str, Any] | None
    feedback: dict[str, Any] | None
    verdict: str | None
    version: int
    created_at: datetime

    model_config = {"from_attributes": True}
