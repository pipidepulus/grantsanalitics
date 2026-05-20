"""RagEvent — records one AI turn for grounding audit and retrieval quality tracking."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RagEvent(Base):
    """One AI turn: captures what the agent retrieved and how long it took.

    Stored per assistant turn so RAG quality can be reviewed offline:
    - Which tools were invoked (file_search / web_search / function tools)
    - Whether file_search (grounded retrieval) was used
    - Response latency in ms
    - The user query that triggered this turn
    """
    __tablename__ = "rag_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True, index=True
    )
    query: Mapped[str] = mapped_column(Text)
    tools_used: Mapped[list | None] = mapped_column(JSON, nullable=True)   # list[str]
    has_file_search: Mapped[bool] = mapped_column(default=False)
    has_web_search: Mapped[bool] = mapped_column(default=False)
    function_tool_count: Mapped[int] = mapped_column(Integer, default=0)
    response_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turn_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
