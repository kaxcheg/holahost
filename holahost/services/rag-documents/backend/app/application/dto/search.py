"""Command and result for chunk search."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchCmd:
    """Command for POST /api/rag-documents/documents/{id}/search."""

    document_id: str
    owner: str
    query: str


@dataclass(frozen=True)
class SearchHitView:
    """A single chunk in a search result, at the use-case boundary (primitives only)."""

    chunk_id: str
    text: str
    page: int | None
    score: float


@dataclass(frozen=True)
class SearchResult:
    """A search's output: chunks sorted by descending similarity, capped at ``SEARCH_TOP_K``.

    An empty list is a valid result, not an error — it signals "no relevant context",
    not "search failed".
    """

    hits: list[SearchHitView]
