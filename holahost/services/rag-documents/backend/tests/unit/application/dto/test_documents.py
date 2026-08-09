"""Tests for document-related DTOs."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from tests._support.builders import make_document

from application.dto.documents import (
    CreateDocumentCmd,
    DeleteDocumentCmd,
    DocumentView,
    GetDocumentCmd,
    ReplaceDocumentCmd,
)


class TestCreateDocumentCmd:
    def test_frozen(self) -> None:
        cmd = CreateDocumentCmd(owner="u", name="n", content=b"x", mime_type="application/pdf")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.name = "other"  # type: ignore[misc]


class TestReplaceDocumentCmd:
    def test_name_defaults_to_none(self) -> None:
        cmd = ReplaceDocumentCmd(
            document_id="id", owner="u", content=b"x", mime_type="application/pdf"
        )
        assert cmd.name is None


class TestGetDocumentCmd:
    def test_frozen(self) -> None:
        cmd = GetDocumentCmd(document_id="id", owner="u")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.owner = "other"  # type: ignore[misc]


class TestDeleteDocumentCmd:
    def test_frozen(self) -> None:
        cmd = DeleteDocumentCmd(document_id="id", owner="u")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.owner = "other"  # type: ignore[misc]


class TestDocumentView:
    def test_of_builds_from_entity(self) -> None:
        document = make_document(owner="u", name="Guidebook.pdf", chunk_count=3)
        view = DocumentView.of(document)
        assert view.document_id == str(document.id)
        assert view.name == "Guidebook.pdf"
        assert view.mime_type == "application/pdf"
        assert view.chunk_count == 3
        assert view.created_at == document.created_at
        assert view.updated_at == document.updated_at

    def test_frozen(self) -> None:
        view = DocumentView(
            document_id="id",
            name="n",
            mime_type="application/pdf",
            chunk_count=1,
            created_at=datetime.now(tz=UTC),
            updated_at=datetime.now(tz=UTC),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            view.name = "other"  # type: ignore[misc]
