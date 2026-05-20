from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import Float, DateTime, ForeignKey, Text, JSON, Uuid, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

if TYPE_CHECKING:
    from app.models.project import Project


class CyranoEvaluation(Base):
    """Persists every structured Cyrano diagnostic run for a project.

    Allows comparing evaluations over time and eliminates the need for
    regex extraction of scores from free-form LLM text.
    """

    __tablename__ = "cyrano_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)

    # Overall weighted score (0–100)
    score: Mapped[float] = mapped_column(Float, nullable=False)

    # Per-section scores: {"problem_definition": 8.5, "problem_tree": 7.0, ...}
    sections: Mapped[dict | None] = mapped_column(JSON)

    # Structured feedback: {"gaps": [...], "recommendations": [...]}
    feedback: Mapped[dict | None] = mapped_column(JSON)

    # Plain-text verdict: "APROBADO" | "EN REVISIÓN"
    verdict: Mapped[str | None] = mapped_column(Text)

    # Sequential evaluation number per project (1 = first run, 2 = second, …)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="cyrano_evaluations")
