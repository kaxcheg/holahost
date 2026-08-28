"""Tests for SearchDocumentUseCase (UC-R3)."""

from __future__ import annotations

import uuid

import pytest
from tests._support.builders import make_document, make_embedding
from tests._support.fakes import (
    FakeDocumentsRepo,
    FakeEmbeddingModel,
    FakeUnitOfWork,
    FakeVectorSearch,
)

from application.dto.search import SearchCmd
from application.exceptions import InvalidPayloadError, NotFoundError
from application.ports.vector import SearchHit, SimilarityScore
from application.use_cases.search_document import SearchDocumentUseCase
from domain.value_objects.chunk_id import ChunkId
from domain.value_objects.document_id import DocumentId
from domain.value_objects.embedding import Embedding
from domain.value_objects.page_number import PageNumber

# The values every infra/envs/<env>/.env carries, so these tests read the way production
# runs. They are arguments now, not constants — see `SearchDocumentUseCase`'s docstring.
SEARCH_TOP_K = 5
SIMILARITY_THRESHOLD = 0.30
MAX_QUERY_LENGTH = 4000


def _uc(
    documents_repo: FakeDocumentsRepo,
    vector_search: FakeVectorSearch | None = None,
    *,
    top_k: int = SEARCH_TOP_K,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
    max_query_length: int = MAX_QUERY_LENGTH,
    uow: FakeUnitOfWork | None = None,
    embedder: FakeEmbeddingModel | None = None,
) -> SearchDocumentUseCase:
    return SearchDocumentUseCase(
        documents_repo_factory=documents_repo,
        embedder=embedder or FakeEmbeddingModel(make_embedding()),
        vector_search_factory=vector_search or FakeVectorSearch(),
        uow=uow or FakeUnitOfWork(),
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        max_query_length=max_query_length,
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
        # Present even here, where nothing was exceeded: US-R09 wants one `details`
        # field set per class, and the applicable limit is a fact worth answering with.
        assert exc.value.limit == MAX_QUERY_LENGTH

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
            def _top_k_impl(
                self, document_id: DocumentId, query: Embedding, k: int, threshold: float
            ) -> list[SearchHit]:
                captured["k"] = k
                captured["threshold"] = threshold
                return []

        cmd = SearchCmd(document_id=str(existing.id), owner="user-123", query="q")
        # Values deliberately unlike the defaults: passing the defaults would pass just as
        # well against a hard-coded literal, which is exactly the bug this now guards.
        _uc(
            FakeDocumentsRepo([existing]),
            _CapturingVectorSearch(),
            top_k=11,
            similarity_threshold=0.99,
        ).execute(cmd)

        assert captured == {"k": 11, "threshold": 0.99}


class TestOneTransactionOneSnapshot:
    """The ownership check and the search share a transaction — see the use case's
    `:raises NotFoundError:`. Two transactions cost two pool checkouts and two
    `_bind_owner()` round trips per search, and left a document deleted between them
    answering `200 {"chunks": []}` instead of `404`."""

    def test_both_reads_run_in_one_transaction(self) -> None:
        existing = make_document(owner="user-123")
        uow = FakeUnitOfWork()
        cmd = SearchCmd(document_id=str(existing.id), owner="user-123", query="q")

        _uc(FakeDocumentsRepo([existing]), uow=uow).execute(cmd)

        assert (uow.commits, uow.rollbacks) == (1, 0)

    def test_missing_document_rolls_the_transaction_back(self) -> None:
        uow = FakeUnitOfWork()
        cmd = SearchCmd(document_id=str(uuid.uuid4()), owner="user-123", query="q")

        with pytest.raises(NotFoundError):
            _uc(FakeDocumentsRepo(), uow=uow).execute(cmd)

        assert (uow.commits, uow.rollbacks) == (0, 1)


class TestQueryIsJudgedBeforeAnyWork:
    def test_invalid_query_never_reaches_the_embedder_or_storage(self) -> None:
        existing = make_document(owner="user-123")
        embedder = FakeEmbeddingModel(make_embedding())
        uow = FakeUnitOfWork()
        cmd = SearchCmd(document_id=str(existing.id), owner="user-123", query="")

        with pytest.raises(InvalidPayloadError):
            _uc(FakeDocumentsRepo([existing]), uow=uow, embedder=embedder).execute(cmd)

        assert embedder.calls == 0
        assert (uow.commits, uow.rollbacks) == (0, 0)

    def test_invalid_query_wins_over_a_missing_document(self) -> None:
        # Deliberate: the query is the caller's own input and is judged without asking
        # storage anything, so it is answered first. Discloses nothing either way — a
        # 422 says as little about whether the id exists as the 404 would.
        cmd = SearchCmd(document_id=str(uuid.uuid4()), owner="user-123", query="   ")

        with pytest.raises(InvalidPayloadError):
            _uc(FakeDocumentsRepo()).execute(cmd)


class TestSearchParametersAreInjected:
    """Regression: all three were module constants, so their `Settings` fields had zero
    readers and the values in `.env` were decorative."""

    def test_configured_max_query_length_is_the_one_enforced(self) -> None:
        existing = make_document(owner="user-123")

        with pytest.raises(InvalidPayloadError) as exc:
            _uc(FakeDocumentsRepo([existing]), max_query_length=10).execute(
                SearchCmd(document_id=str(existing.id), owner="user-123", query="x" * 11)
            )

        assert exc.value.limit == 10
