import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Text, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class CallSpec(Base):
    __tablename__ = "call_specs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(Text)
    extracted_requirements: Mapped[dict | None] = mapped_column(JSON)
    eligibility_criteria: Mapped[str | None] = mapped_column(Text)
    max_amount: Mapped[str | None] = mapped_column(String(255))
    counterpart_required: Mapped[str | None] = mapped_column(String(255))
    deadline: Mapped[str | None] = mapped_column(String(255))
    mandatory_sections: Mapped[dict | None] = mapped_column(JSON)
    raw_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    projects: Mapped[list["Project"]] = relationship(back_populates="call_spec", lazy="selectin")
