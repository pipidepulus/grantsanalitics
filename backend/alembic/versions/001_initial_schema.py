"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("organization", sa.String(500)),
        sa.Column("sector", sa.String(255)),
        sa.Column("territory", sa.String(255)),
        sa.Column("preferences", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Call Specs
    op.create_table(
        "call_specs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source_url", sa.Text),
        sa.Column("extracted_requirements", JSONB),
        sa.Column("eligibility_criteria", sa.Text),
        sa.Column("max_amount", sa.String(255)),
        sa.Column("counterpart_required", sa.String(255)),
        sa.Column("deadline", sa.String(255)),
        sa.Column("mandatory_sections", JSONB),
        sa.Column("raw_text", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Projects
    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("status", sa.String(50), server_default="draft"),
        sa.Column("cyrano_score", sa.Float),
        sa.Column("language", sa.String(10), server_default="es"),
        sa.Column("json_data", JSONB),
        sa.Column("problem_definition", sa.Text),
        sa.Column("problem_tree", JSONB),
        sa.Column("objectives_tree", JSONB),
        sa.Column("value_chain", JSONB),
        sa.Column("timeline", JSONB),
        sa.Column("budget", JSONB),
        sa.Column("call_spec_id", UUID(as_uuid=True), sa.ForeignKey("call_specs.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Generated Documents
    op.create_table(
        "generated_docs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("binary_file", sa.LargeBinary, nullable=False),
        sa.Column("version_number", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Conversations
    op.create_table(
        "conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id")),
        sa.Column("title", sa.String(500), server_default="Nueva conversación"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Messages
    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tool_calls", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("generated_docs")
    op.drop_table("projects")
    op.drop_table("call_specs")
    op.drop_table("users")
