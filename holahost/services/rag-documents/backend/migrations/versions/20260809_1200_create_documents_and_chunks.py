"""create documents and chunks

Revision ID: 20260809_1200
Revises:
Create Date: 2026-08-09 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from domain.value_objects.embedding import EMBEDDING_DIM

revision = "20260809_1200"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_subject", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("mime_type", sa.Text, nullable=False),
        sa.Column("chunk_count", sa.Integer, nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.CheckConstraint("btrim(name) <> ''", name="documents_name_not_blank"),
        sa.CheckConstraint("chunk_count >= 1", name="documents_chunk_count_positive"),
        sa.CheckConstraint("updated_at >= created_at", name="documents_updated_not_before"),
    )
    op.create_index("idx_documents_owner_subject", "documents", ["owner_subject"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idx", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("page", sa.Integer, nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.CheckConstraint("idx >= 0", name="chunks_idx_non_negative"),
        sa.CheckConstraint("btrim(text) <> ''", name="chunks_text_not_blank"),
        sa.CheckConstraint("page IS NULL OR page >= 1", name="chunks_page_positive"),
        sa.UniqueConstraint("document_id", "idx", name="chunks_document_idx_uniq"),
    )
    op.create_index("idx_chunks_document_id", "chunks", ["document_id"])

    # Postgres RLS is the sole enforcement of "an owner never sees/writes another
    # owner's row" — repos do not filter by owner in application code. FORCE
    # is required alongside ENABLE: by default RLS does not apply to a table's
    # owning role, only to other roles. A true superuser connection bypasses RLS
    # unconditionally regardless of FORCE — that boundary is enforced by which role
    # the application connects as, not by anything in this migration.
    op.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE documents FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY owner_isolation ON documents
        USING (owner_subject = current_setting('app.current_owner', true))
        WITH CHECK (owner_subject = current_setting('app.current_owner', true))
        """
    )

    # chunks has no owner column of its own — it is subordinate to documents and has no
    # repository of its own — so its policy re-derives ownership through the parent row,
    # which is itself already RLS-filtered in the same transaction.
    op.execute("ALTER TABLE chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chunks FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY owner_isolation ON chunks
        USING (document_id IN (SELECT id FROM documents))
        WITH CHECK (document_id IN (SELECT id FROM documents))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY owner_isolation ON chunks")
    op.execute("DROP POLICY owner_isolation ON documents")

    op.drop_table("chunks")
    op.drop_table("documents")
    op.execute("DROP EXTENSION IF EXISTS vector")
