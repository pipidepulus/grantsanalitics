from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Float, DateTime, ForeignKey, Text, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.enums import ProjectStatus, ProjectLanguage

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.call_spec import CallSpec
    from app.models.document import GeneratedDoc, UploadedDocument
    from app.models.cyrano_evaluation import CyranoEvaluation


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(50), default=ProjectStatus.draft)
    cyrano_score: Mapped[float | None] = mapped_column(Float)
    language: Mapped[str] = mapped_column(String(10), default=ProjectLanguage.es)

    # Complete project data structure
    json_data: Mapped[dict | None] = mapped_column(JSON)

    # Methodology sections
    problem_definition: Mapped[str | None] = mapped_column(Text)
    problem_tree: Mapped[dict | None] = mapped_column(JSON)
    objectives_tree: Mapped[dict | None] = mapped_column(JSON)
    value_chain: Mapped[dict | None] = mapped_column(JSON)
    timeline: Mapped[dict | None] = mapped_column(JSON)
    budget: Mapped[dict | None] = mapped_column(JSON)

    call_spec_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("call_specs.id"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="projects")
    call_spec: Mapped["CallSpec | None"] = relationship(back_populates="projects")
    generated_docs: Mapped[list["GeneratedDoc"]] = relationship(back_populates="project", lazy="selectin")
    uploaded_documents: Mapped[list["UploadedDocument"]] = relationship(back_populates="project", lazy="selectin")
    cyrano_evaluations: Mapped[list["CyranoEvaluation"]] = relationship(
        back_populates="project", lazy="selectin", order_by="CyranoEvaluation.version"
    )
