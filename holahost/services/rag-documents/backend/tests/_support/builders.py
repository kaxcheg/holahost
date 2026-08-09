"""Builders for valid domain objects, used across application-layer tests."""

from __future__ import annotations

from datetime import UTC, datetime

from application.ports.ingestion import TextFragment
from domain.entities.chunk import Chunk
from domain.entities.document import Document
from domain.value_objects.chunk_index import ChunkIndex
from domain.value_objects.document_id import DocumentId
from domain.value_objects.document_name import DocumentName
from domain.value_objects.embedding import EMBEDDING_DIM, Embedding
from domain.value_objects.mime_type import MimeType
from domain.value_objects.owner_subject import OwnerSubject
from domain.value_objects.page_number import PageNumber


def make_embedding() -> Embedding:
    """A valid, L2-normalized embedding vector."""
    vector = [0.0] * EMBEDDING_DIM
    vector[0] = 1.0
    return Embedding(tuple(vector))


def make_document(
    *,
    owner: str = "user-123",
    name: str = "Guidebook.pdf",
    mime_type: str = "application/pdf",
    chunk_count: int = 1,
) -> Document:
    """A valid, already-persisted ``Document`` (uses ``from_repo``, no re-validation)."""
    now = datetime.now(tz=UTC)
    return Document.from_repo(
        id=DocumentId.new(),
        owner=OwnerSubject(owner),
        name=DocumentName(name),
        mime_type=MimeType(mime_type),
        chunk_count=chunk_count,
        created_at=now,
        updated_at=now,
    )


def make_chunk(
    *,
    document_id: DocumentId | None = None,
    index: int = 0,
    text: str = "chunk text",
    page: int | None = 1,
) -> Chunk:
    """A valid ``Chunk``, freshly created."""
    return Chunk.create(
        document_id=document_id or DocumentId.new(),
        index=ChunkIndex(index),
        text=text,
        embedding=make_embedding(),
        page=PageNumber(page),
    )


def make_text_fragment(text: str = "fragment text", page: int | None = 1) -> TextFragment:
    """A valid ``TextFragment``."""
    return TextFragment(text=text, page=PageNumber(page))


__all__ = ["make_chunk", "make_document", "make_embedding", "make_text_fragment"]
