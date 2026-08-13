"""Protocol for similarity search over a document's chunks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from application.ports.uow import UnitOfWork
from domain.value_objects.chunk_id import ChunkId
from domain.value_objects.document_id import DocumentId
from domain.value_objects.embedding import Embedding
from domain.value_objects.owner_subject import OwnerSubject
from domain.value_objects.page_number import PageNumber


@dataclass(frozen=True, slots=True)
class SimilarityScore:
    """Cosine similarity between two L2-normalized vectors — in [-1, 1].

    An application-layer pipeline-transit type, not a domain value object: it belongs
    to the query↔chunk pair, not to any persisted entity, and never becomes a `Chunk`
    field — it exists only to carry a computed value alongside a `SearchHit`.

    :param value: The cosine similarity.
    """

    value: float

    def __post_init__(self) -> None:
        # Search-time computed, not client input — out-of-range is an
        # internal defect, so plain ValueError.
        if not (-1.0 <= self.value <= 1.0):
            raise ValueError("SimilarityScore must be in range [-1, 1]")


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A single chunk returned by :meth:`VectorSearch.top_k`, with its similarity score.

    A projection, not a duplicate of ``Chunk``: the entity's invariant forces it to
    carry its embedding, which a search response has no reason to return, so
    ``VectorSearch`` hands back this narrower shape instead of the entity itself (§8.0).
    """

    chunk_id: ChunkId
    text: str
    page: PageNumber
    score: SimilarityScore


class VectorSearch(ABC):
    """Cosine-similarity search over one document's chunks — read side of Chunk
    (``DocumentsRepo`` is the write side). CQRS-justified as its own port despite
    ``Chunk`` having no repo of its own (§4.3): this returns a narrow projection
    (``SearchHit``), never reconstructs the entity, so it is not "a chunk
    repository" in the sense that would need folding into the aggregate's repo.

    ``owner`` is bound at construction, same reasoning and same shape as
    ``DocumentsRepo``: ``top_k`` is concrete and calls ``_bind_owner()`` before
    delegating to ``_top_k_impl``, so a subclass cannot reach storage unscoped.
    """

    def __init__(self, uow: UnitOfWork, owner: OwnerSubject) -> None:
        self._uow = uow
        self._owner = owner

    @abstractmethod
    def _bind_owner(self) -> None:
        """Scope the active transaction to the owner this search was constructed
        with (§8.0)."""
        ...

    def top_k(
        self, document_id: DocumentId, query: Embedding, k: int, threshold: float
    ) -> list[SearchHit]:
        """Return up to ``k`` chunks of ``document_id`` most similar to ``query``,
        scoped to the owner this search was constructed with.

        Args:
            document_id: The document to search within.
            query: The (already L2-normalized) query embedding.
            k: Maximum number of hits to return.
            threshold: Minimum cosine similarity; less-similar chunks are excluded.

        Returns:
            Hits sorted by descending similarity, capped at ``k``. Empty if nothing
            clears ``threshold``, or if ``document_id`` belongs to another owner
            (US-R06, A-13) — a valid, non-error result either way.

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: a concurrent write conflicted with this read.
            IntegrityError: a stored invariant was violated (internal defect).
        """
        self._bind_owner()
        return self._top_k_impl(document_id, query, k, threshold)

    @abstractmethod
    def _top_k_impl(
        self, document_id: DocumentId, query: Embedding, k: int, threshold: float
    ) -> list[SearchHit]: ...


VectorSearchFactory = Callable[[OwnerSubject], VectorSearch]
"""Builds an owner-bound ``VectorSearch`` — same reasoning as ``DocumentsRepoFactory``."""
