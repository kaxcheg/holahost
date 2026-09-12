"""Tests for the test fakes themselves — for the two contracts they exist to protect:
"every repository call runs inside an explicit `with uow:`", and owner scoping.

Both are falsifiable only if the fakes enforce them. A fake that returns its preset hits
regardless of owner, or that constructs a ``FakeUnitOfWork`` of its own instead of the one
the use case was injected with, lets a use case drop its transaction or ask the factory
for the wrong subject and still pass the entire unit suite.
"""

from __future__ import annotations

import pytest
from tests._support.builders import make_document, make_embedding
from tests._support.fakes import FakeDocumentsRepo, FakeUnitOfWork, FakeVectorSearch

from application.ports.vector import SearchHit, SimilarityScore
from domain.value_objects.chunk_id import ChunkId
from domain.value_objects.owner_subject import OwnerSubject
from domain.value_objects.page_number import PageNumber

_OWNER = OwnerSubject("user-123")
_OTHER_OWNER = OwnerSubject("user-999")


def _hit() -> SearchHit:
    return SearchHit(
        chunk_id=ChunkId.new(),
        text="Check-in from 15:00",
        page=PageNumber(1),
        score=SimilarityScore(0.7),
    )


class TestCallsMustRunInsideATransaction:
    def test_repository_read_outside_a_unit_of_work_fails(self) -> None:
        document = make_document(owner=str(_OWNER.value))
        repo = FakeDocumentsRepo([document])

        with pytest.raises(AssertionError, match="outside an open UnitOfWork"):
            repo.get(document.id)

    def test_repository_write_outside_a_unit_of_work_fails(self) -> None:
        document = make_document(owner=str(_OWNER.value))

        with pytest.raises(AssertionError, match="outside an open UnitOfWork"):
            FakeDocumentsRepo().add(document)

    def test_vector_search_outside_a_unit_of_work_fails(self) -> None:
        document = make_document(owner=str(_OWNER.value))

        with pytest.raises(AssertionError, match="outside an open UnitOfWork"):
            FakeVectorSearch([_hit()]).top_k(document.id, make_embedding(), 5, 0.3)

    def test_inside_one_it_passes(self) -> None:
        document = make_document(owner=str(_OWNER.value))
        repo = FakeDocumentsRepo([document])

        with FakeUnitOfWork():
            assert repo.get(document.id) == document

    def test_the_open_marker_is_released_even_when_the_body_raises(self) -> None:
        uow = FakeUnitOfWork()
        with pytest.raises(RuntimeError), uow:
            raise RuntimeError("boom")

        assert (uow.commits, uow.rollbacks) == (0, 1)
        assert not FakeUnitOfWork.any_open()


class TestOwnerScoping:
    def test_the_factory_rebinds_the_owner_it_is_called_with(self) -> None:
        document = make_document(owner=str(_OWNER.value))
        repo = FakeDocumentsRepo([document])

        bound = repo(_OTHER_OWNER)

        assert repo.factory_owners == [_OTHER_OWNER]
        with FakeUnitOfWork():
            # Indistinguishable from "does not exist", exactly as the real adapter is.
            assert bound.get(document.id) is None

    def test_vector_search_serves_no_hits_to_another_owner(self) -> None:
        document = make_document(owner=str(_OWNER.value))
        search = FakeVectorSearch([_hit()], owner=_OWNER)

        with FakeUnitOfWork():
            assert len(search.top_k(document.id, make_embedding(), 5, 0.3)) == 1
            assert search(_OTHER_OWNER).top_k(document.id, make_embedding(), 5, 0.3) == []

    def test_vector_search_records_what_it_was_asked_for(self) -> None:
        document = make_document(owner=str(_OWNER.value))
        search = FakeVectorSearch()

        with FakeUnitOfWork():
            search.top_k(document.id, make_embedding(), 11, 0.99)

        assert search.calls == [(document.id, 11, 0.99)]
