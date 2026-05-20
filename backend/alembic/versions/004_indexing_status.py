"""add indexing_status to uploaded_documents

Revision ID: 004
Revises: 003
Create Date: 2026-05-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "uploaded_documents",
        sa.Column(
            "indexing_status",
            sa.String(20),
            nullable=False,
            server_default="indexed",  # Existing rows are already indexed
        ),
    )


def downgrade() -> None:
    op.drop_column("uploaded_documents", "indexing_status")
