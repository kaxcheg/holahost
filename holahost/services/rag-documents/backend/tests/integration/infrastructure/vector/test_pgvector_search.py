from __future__ import annotations

import pytest

from domain.entities.chunk import Chunk
from domain.entities.document import Document
from domain.value_objects.chunk_index import ChunkIndex
from domain.value_objects.document_id import DocumentId
from domain.value_objects.document_name import DocumentName
from domain.value_objects.embedding import EMBEDDING_DIM, Embedding
from domain.value_objects.mime_type import MimeType
from domain.value_objects.owner_subject import OwnerSubject
from domain.value_objects.page_number import PageNumber
from infrastructure.db.sqlalchemy_documents_repo import SqlAlchemyDocumentsRepo
from infrastructure.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork
from infrastructure.vector.pgvector_search import PgvectorSearch

pytestmark = pytest.mark.integration

_OWNER = OwnerSubject("user-1")


def _unit_vector(hot_index: int) -> Embedding:
    vector = [0.0] * EMBEDDING_DIM
    vector[hot_index] = 1.0
    return Embedding(tuple(vector))


def _document(fragments: list[tuple[str, Embedding]], *, owner: OwnerSubject = _OWNER) -> Document:
    document_id = DocumentId.new()
    chunks = [
        Chunk.create(
            document_id=document_id,
            index=ChunkIndex(i),
            text=text,
            embedding=embedding,
            page=PageNumber(1),
        )
        for i, (text, embedding) in enumerate(fragments)
    ]
    return Document.create(
        id=document_id,
        owner=owner,
        name=DocumentName("Doc.pdf"),
        mime_type=MimeType("application/pdf"),
        chunks=chunks,
    )


def test_returns_hits_above_threshold_sorted_desc(uow: SqlAlchemyUnitOfWork) -> None:
    # Two orthogonal unit vectors -> cosine similarity to the query is exactly 1.0 for
    # the matching chunk and 0.0 for the other, so sort order is unambiguous.
    documents_repo = SqlAlchemyDocumentsRepo(uow, _OWNER)
    search = PgvectorSearch(uow, _OWNER)
    document = _document([("close", _unit_vector(0)), ("far", _unit_vector(1))])
    with uow:
        documents_repo.add(document)
    with uow:
        hits = search.top_k(document.id, _unit_vector(0), k=5, threshold=-1.0)
    assert [h.text for h in hits] == ["close", "far"]
    assert hits[0].score.value == pytest.approx(1.0)
    assert hits[1].score.value == pytest.approx(0.0)


def test_empty_result_when_nothing_meets_threshold(uow: SqlAlchemyUnitOfWork) -> None:
    documents_repo = SqlAlchemyDocumentsRepo(uow, _OWNER)
    search = PgvectorSearch(uow, _OWNER)
    document = _document([("chunk text", _unit_vector(0))])
    with uow:
        documents_repo.add(document)
    with uow:
        hits = search.top_k(document.id, _unit_vector(1), k=5, threshold=0.99)
    assert hits == []


def test_respects_k_cap(uow: SqlAlchemyUnitOfWork) -> None:
    documents_repo = SqlAlchemyDocumentsRepo(uow, _OWNER)
    search = PgvectorSearch(uow, _OWNER)
    document = _document([(f"chunk {i}", _unit_vector(0)) for i in range(3)])
    with uow:
        documents_repo.add(document)
    with uow:
        hits = search.top_k(document.id, _unit_vector(0), k=2, threshold=-1.0)
    assert len(hits) == 2


def test_scoped_to_document_id(uow: SqlAlchemyUnitOfWork) -> None:
    documents_repo = SqlAlchemyDocumentsRepo(uow, _OWNER)
    search = PgvectorSearch(uow, _OWNER)
    doc_a = _document([("a", _unit_vector(0))])
    doc_b = _document([("b", _unit_vector(0))])
    with uow:
        documents_repo.add(doc_a)
        documents_repo.add(doc_b)
    with uow:
        hits = search.top_k(doc_a.id, _unit_vector(0), k=5, threshold=-1.0)
    assert len(hits) == 1
    assert hits[0].text == "a"


def test_search_for_wrong_owner_returns_no_hits(uow: SqlAlchemyUnitOfWork) -> None:
    """Proves VectorSearch is RLS-scoped too, not just DocumentsRepo (§8.0) — a
    search bound to a different owner sees nothing, even though the chunks
    genuinely exist and would otherwise match."""
    documents_repo = SqlAlchemyDocumentsRepo(uow, _OWNER)
    document = _document([("secret", _unit_vector(0))])
    with uow:
        documents_repo.add(document)

    other_search = PgvectorSearch(uow, OwnerSubject("someone-else"))
    with uow:
        hits = other_search.top_k(document.id, _unit_vector(0), k=5, threshold=-1.0)
    assert hits == []
