"""Tests for DeleteDocumentUseCase (UC-R5)."""

from __future__ import annotations

import uuid

import pytest
from tests._support.builders import make_document
from tests._support.fakes import FakeDocumentsRepo, FakeUnitOfWork

from application.dto.documents import DeleteDocumentCmd
from application.exceptions import NotFoundError
from application.ports.exceptions import ConcurrentUpdateError
from application.use_cases.delete_document import DeleteDocumentUseCase
from domain.entities.document import Document
from domain.value_objects.document_id import DocumentId


class TestDeleteDocumentUseCase:
    def test_deletes_document(self) -> None:
        existing = make_document(owner="user-123")
        documents_repo = FakeDocumentsRepo([existing])
        uc = DeleteDocumentUseCase(documents_repo_factory=documents_repo, uow=FakeUnitOfWork())

        uc.execute(DeleteDocumentCmd(document_id=str(existing.id), owner="user-123"))

        assert documents_repo.deleted == [existing.id]

    def test_missing_document_raises_not_found(self) -> None:
        uc = DeleteDocumentUseCase(documents_repo_factory=FakeDocumentsRepo(), uow=FakeUnitOfWork())
        with pytest.raises(NotFoundError):
            uc.execute(DeleteDocumentCmd(document_id=str(uuid.uuid4()), owner="user-123"))

    def test_repeated_delete_is_idempotent_by_effect(self) -> None:
        existing = make_document(owner="user-123")
        documents_repo = FakeDocumentsRepo([existing])
        uc = DeleteDocumentUseCase(documents_repo_factory=documents_repo, uow=FakeUnitOfWork())
        cmd = DeleteDocumentCmd(document_id=str(existing.id), owner="user-123")

        uc.execute(cmd)
        with pytest.raises(NotFoundError):
            uc.execute(cmd)

    def test_retries_once_on_concurrent_update_then_succeeds(self) -> None:
        existing = make_document(owner="user-123")

        class _FlakyDocumentsRepo(FakeDocumentsRepo):
            def __init__(self) -> None:
                super().__init__([existing])
                self._locked_gets = 0

            def _get_impl(self, document_id: DocumentId, *, lock: bool) -> Document | None:
                if lock:
                    self._locked_gets += 1
                    if self._locked_gets == 1:
                        raise ConcurrentUpdateError
                return super()._get_impl(document_id, lock=lock)

        documents_repo = _FlakyDocumentsRepo()
        uc = DeleteDocumentUseCase(documents_repo_factory=documents_repo, uow=FakeUnitOfWork())
        uc.execute(DeleteDocumentCmd(document_id=str(existing.id), owner="user-123"))
        assert documents_repo.deleted == [existing.id]

    def test_gives_up_after_two_retries(self) -> None:
        existing = make_document(owner="user-123")

        class _AlwaysConflictingDocumentsRepo(FakeDocumentsRepo):
            def _get_impl(self, document_id: DocumentId, *, lock: bool) -> Document | None:
                if lock:
                    raise ConcurrentUpdateError
                return super()._get_impl(document_id, lock=lock)

        documents_repo = _AlwaysConflictingDocumentsRepo([existing])
        uc = DeleteDocumentUseCase(documents_repo_factory=documents_repo, uow=FakeUnitOfWork())
        with pytest.raises(ConcurrentUpdateError):
            uc.execute(DeleteDocumentCmd(document_id=str(existing.id), owner="user-123"))
