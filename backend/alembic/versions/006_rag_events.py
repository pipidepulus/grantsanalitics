"""add rag_events table

Revision ID: 006
Revises: 005
Create Date: 2026-05-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rag_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("tools_used", sa.JSON, nullable=True),
        sa.Column("has_file_search", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_web_search", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("function_tool_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("response_latency_ms", sa.Integer, nullable=True),
        sa.Column("turn_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("rag_events")
