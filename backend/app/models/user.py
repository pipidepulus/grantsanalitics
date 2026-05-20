import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, JSON, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    organization: Mapped[str | None] = mapped_column(String(500))
    sector: Mapped[str | None] = mapped_column(String(255))
    territory: Mapped[str | None] = mapped_column(String(255))
    preferences: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    projects: Mapped[list["Project"]] = relationship(back_populates="user", lazy="selectin")
    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user", lazy="selectin")
