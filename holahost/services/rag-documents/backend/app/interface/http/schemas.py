"""Pydantic request/response models — the wire shapes of spec §7.2-§7.5."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from application.dto.documents import DocumentView
from application.dto.search import SearchResult


class DocumentResponse(BaseModel):
    """The one document representation shared by create, replace, and read (§7.2)."""

    document_id: str
    name: str
    mime_type: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_view(cls, view: DocumentView) -> DocumentResponse:
        return cls(
            document_id=view.document_id,
            name=view.name,
            mime_type=view.mime_type,
            chunk_count=view.chunk_count,
            created_at=view.created_at,
            updated_at=view.updated_at,
        )


class SearchRequest(BaseModel):
    """Body of POST .../search (§7.3). No length/emptiness constraints here —
    deliberately: those are business rules already enforced by
    `SearchDocumentUseCase` (`InvalidPayloadError`), routed through the same envelope
    as every other application error. Duplicating them here would raise Pydantic's own
    `RequestValidationError` for the *value* checks too, which is a different (though
    still envelope-mapped, see `errors.py`) code path for no benefit.
    """

    query: str


class SearchHitResponse(BaseModel):
    chunk_id: str
    text: str
    page: int | None
    score: float


class SearchResponse(BaseModel):
    chunks: list[SearchHitResponse]

    @classmethod
    def from_result(cls, result: SearchResult) -> SearchResponse:
        return cls(
            chunks=[
                SearchHitResponse(chunk_id=h.chunk_id, text=h.text, page=h.page, score=h.score)
                for h in result.hits
            ]
        )


class HealthResponse(BaseModel):
    status: str
