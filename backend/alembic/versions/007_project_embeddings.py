"""add document_embeddings table with pgvector

Revision ID: 007
Revises: 006
Create Date: 2026-05-31

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector

revision = "007"
down_revision = "006"


def upgrade() -> None:
    # 1. Crear extensión vector si no existe
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Crear tabla document_embeddings
    op.create_table(
        "document_embeddings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_doc_id", UUID(as_uuid=True), sa.ForeignKey("uploaded_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(768), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 3. Índices
    op.execute("CREATE INDEX ON document_embeddings USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX ON document_embeddings USING GIN (metadata)")
    op.create_index("idx_doc_emb_project", "document_embeddings", ["project_id"])

    # 4. Columna embedding_id en uploaded_documents
    op.add_column("uploaded_documents", sa.Column("embedding_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_uploaded_doc_embedding",
        "uploaded_documents", "document_embeddings",
        ["embedding_id"], ["id"],
        ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_uploaded_doc_embedding", "uploaded_documents", type_="foreignkey")
    op.drop_column("uploaded_documents", "embedding_id")
    op.drop_index("idx_doc_emb_project", "document_embeddings")
    op.drop_table("document_embeddings")
