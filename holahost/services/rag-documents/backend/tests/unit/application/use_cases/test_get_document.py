"""Tests for GetDocumentUseCase."""

from __future__ import annotations

import uuid

import pytest
from tests._support.builders import make_document
from tests._support.fakes import FakeDocumentsRepo, FakeUnitOfWork

from application.dto.documents import GetDocumentCmd
from application.exceptions import NotFoundError
from application.use_cases.get_document import GetDocumentUseCase


class TestGetDocumentUseCase:
    def test_returns_document_view(self) -> None:
        existing = make_document(owner="user-123", name="Guidebook.pdf")
        uc = GetDocumentUseCase(
            documents_repo_factory=FakeDocumentsRepo([existing]), uow=FakeUnitOfWork()
        )

        view = uc.execute(GetDocumentCmd(document_id=str(existing.id), owner="user-123"))

        assert view.document_id == str(existing.id)
        assert view.name == "Guidebook.pdf"

    def test_missing_document_raises_not_found(self) -> None:
        uc = GetDocumentUseCase(documents_repo_factory=FakeDocumentsRepo(), uow=FakeUnitOfWork())
        with pytest.raises(NotFoundError):
            uc.execute(GetDocumentCmd(document_id=str(uuid.uuid4()), owner="user-123"))

    def test_other_owners_document_raises_not_found(self) -> None:
        existing = make_document(owner="someone-else")
        uc = GetDocumentUseCase(
            documents_repo_factory=FakeDocumentsRepo([existing]), uow=FakeUnitOfWork()
        )
        with pytest.raises(NotFoundError):
            uc.execute(GetDocumentCmd(document_id=str(existing.id), owner="user-123"))
