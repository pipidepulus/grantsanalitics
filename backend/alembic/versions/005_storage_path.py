"""add storage_path to uploaded_documents and generated_docs

Revision ID: 005
Revises: 004
Create Date: 2026-05-02

Adds a ``storage_path`` column to both document tables.  New documents write
their bytes to the object storage backend and record the key here.  Existing
rows keep their ``binary_file`` content; the download route falls back to
``binary_file`` when ``storage_path`` is NULL so old data continues to work.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "uploaded_documents",
        sa.Column("storage_path", sa.String(1000), nullable=True),
    )
    op.add_column(
        "generated_docs",
        sa.Column("storage_path", sa.String(1000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("uploaded_documents", "storage_path")
    op.drop_column("generated_docs", "storage_path")
