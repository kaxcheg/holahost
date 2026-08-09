"""Tests for SearchDocumentUseCase (UC-R3)."""

from __future__ import annotations

import uuid

import pytest
from tests._support.builders import make_document, make_embedding
from tests._support.fakes import FakeDocumentsRepo, FakeEmbeddingModel, FakeVectorSearch

from application.dto.search import SearchCmd
from application.exceptions import InvalidPayloadError, NotFoundError
from application.limits import MAX_QUERY_LENGTH, SEARCH_TOP_K, SIMILARITY_THRESHOLD
from application.ports.vector import SearchHit, SimilarityScore
from application.use_cases.search_document import SearchDocumentUseCase
from domain.value_objects.chunk_id import ChunkId
from domain.value_objects.document_id import DocumentId
from domain.value_objects.embedding import Embedding
from domain.value_objects.page_number import PageNumber


def _uc(
    documents_repo: FakeDocumentsRepo, vector_search: FakeVectorSearch | None = None
) -> SearchDocumentUseCase:
    return SearchDocumentUseCase(
        documents_repo=documents_repo,
        embedder=FakeEmbeddingModel(make_embedding()),
        vector_search=vector_search or FakeVectorSearch(),
    )


class TestSearchDocumentUseCase:
    def test_returns_translated_hits(self) -> None:
        existing = make_document(owner="user-123")
        hit = SearchHit(
            chunk_id=ChunkId.new(),
            text="Check-in from 15:00",
            page=PageNumber(2),
            score=SimilarityScore(0.71),
        )
        documents_repo = FakeDocumentsRepo([existing])
        vector_search = FakeVectorSearch([hit])
        cmd = SearchCmd(document_id=str(existing.id), owner="user-123", query="check-in time")

        result = _uc(documents_repo, vector_search).execute(cmd)

        assert len(result.hits) == 1
        assert result.hits[0].chunk_id == str(hit.chunk_id)
        assert result.hits[0].page == 2
        assert result.hits[0].score == 0.71

    def test_empty_hits_is_a_valid_result(self) -> None:
        existing = make_document(owner="user-123")
        documents_repo = FakeDocumentsRepo([existing])
        cmd = SearchCmd(document_id=str(existing.id), owner="user-123", query="anything")

        result = _uc(documents_repo).execute(cmd)

        assert result.hits == []

    def test_search_on_missing_document_raises_not_found(self) -> None:
        cmd = SearchCmd(document_id=str(uuid.uuid4()), owner="user-123", query="q")
        with pytest.raises(NotFoundError):
            _uc(FakeDocumentsRepo()).execute(cmd)

    def test_rejects_empty_query(self) -> None:
        existing = make_document(owner="user-123")
        cmd = SearchCmd(document_id=str(existing.id), owner="user-123", query="   ")
        with pytest.raises(InvalidPayloadError) as exc:
            _uc(FakeDocumentsRepo([existing])).execute(cmd)
        assert exc.value.field == "query"
        assert exc.value.limit is None

    def test_rejects_query_over_max_length(self) -> None:
        existing = make_document(owner="user-123")
        cmd = SearchCmd(
            document_id=str(existing.id), owner="user-123", query="x" * (MAX_QUERY_LENGTH + 1)
        )
        with pytest.raises(InvalidPayloadError) as exc:
            _uc(FakeDocumentsRepo([existing])).execute(cmd)
        assert exc.value.limit == MAX_QUERY_LENGTH

    def test_uses_configured_top_k_and_threshold(self) -> None:
        existing = make_document(owner="user-123")
        captured: dict[str, object] = {}

        class _CapturingVectorSearch(FakeVectorSearch):
            def top_k(
                self, document_id: DocumentId, query: Embedding, k: int, threshold: float
            ) -> list[SearchHit]:
                captured["k"] = k
                captured["threshold"] = threshold
                return []

        cmd = SearchCmd(document_id=str(existing.id), owner="user-123", query="q")
        _uc(FakeDocumentsRepo([existing]), _CapturingVectorSearch()).execute(cmd)

        assert captured == {"k": SEARCH_TOP_K, "threshold": SIMILARITY_THRESHOLD}
