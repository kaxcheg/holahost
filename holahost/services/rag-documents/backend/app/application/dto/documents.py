"""Commands and views for create/replace/read of a document (spec §8.2, §8.5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.entities.document import Document


@dataclass(frozen=True)
class CreateDocumentCmd:
    """Command for POST /api/rag-documents/documents (UC-R1).

    ``mime_type`` is the content-sniffed MIME type, not the client's declared
    Content-Type header (§3.8) — sniffing happens in the interface layer before this
    command is constructed.
    """

    owner: str
    name: str
    content: bytes
    mime_type: str


@dataclass(frozen=True)
class ReplaceDocumentCmd:
    """Command for PUT /api/rag-documents/documents/{id} (UC-R2)."""

    document_id: str
    owner: str
    content: bytes
    mime_type: str
    name: str | None = None


@dataclass(frozen=True)
class GetDocumentCmd:
    """Command for GET /api/rag-documents/documents/{id} (UC-R4)."""

    document_id: str
    owner: str


@dataclass(frozen=True)
class DeleteDocumentCmd:
    """Command for DELETE /api/rag-documents/documents/{id} (UC-R5)."""

    document_id: str
    owner: str


@dataclass(frozen=True)
class DocumentView:
    """The one representation of a document — shared by create, replace, and read
    (spec §8.2): only the response code differs, never the response shape.
    """

    document_id: str
    name: str
    mime_type: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, document: Document) -> DocumentView:
        """Build the view from a domain ``Document`` entity."""
        return cls(
            document_id=str(document.id),
            name=document.name.value,
            mime_type=document.mime_type.value,
            chunk_count=document.chunk_count,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )
