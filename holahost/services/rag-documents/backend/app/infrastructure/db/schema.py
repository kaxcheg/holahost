"""Single source of truth for the relational schema (spec §6).

These ``Table`` objects drive both the Core queries in the repository adapters and the
Alembic migrations (``migrations/env.py`` exposes ``metadata`` as ``target_metadata``).
Domain entities stay persistence-ignorant — the column<->attribute bridge and
value-object conversion live in each adapter's in-module data mapper, not here.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

from domain.value_objects.embedding import EMBEDDING_DIM

metadata = MetaData()

documents = Table(
    "documents",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("owner_subject", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("mime_type", Text, nullable=False),
    Column("chunk_count", Integer, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False),
    CheckConstraint("btrim(name) <> ''", name="documents_name_not_blank"),
    CheckConstraint("chunk_count >= 1", name="documents_chunk_count_positive"),
    CheckConstraint("updated_at >= created_at", name="documents_updated_not_before"),
)

chunks = Table(
    "chunks",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "document_id",
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("idx", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("page", Integer, nullable=True),
    Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
    CheckConstraint("idx >= 0", name="chunks_idx_non_negative"),
    CheckConstraint("btrim(text) <> ''", name="chunks_text_not_blank"),
    CheckConstraint("page IS NULL OR page >= 1", name="chunks_page_positive"),
    UniqueConstraint("document_id", "idx", name="chunks_document_idx_uniq"),
)

Index("idx_documents_owner_subject", documents.c.owner_subject)
Index("idx_chunks_document_id", chunks.c.document_id)
