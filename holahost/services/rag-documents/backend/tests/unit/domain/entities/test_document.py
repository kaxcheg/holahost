from datetime import UTC, datetime

import pytest

from domain.entities.document import MAX_CHUNKS_PER_DOCUMENT, Document
from domain.exceptions import DomainValidationError
from domain.value_objects.document_id import DocumentId
from domain.value_objects.document_name import DocumentName
from domain.value_objects.mime_type import MimeType
from domain.value_objects.owner_subject import OwnerSubject

_OWNER = OwnerSubject("user-123")
_NAME = DocumentName("Guidebook.pdf")
_MIME = MimeType("application/pdf")


class TestDocument:
    def test_create_sets_fields_and_matching_timestamps(self) -> None:
        doc = Document.create(owner=_OWNER, name=_NAME, mime_type=_MIME, chunk_count=3)
        assert doc.owner == _OWNER
        assert doc.name == _NAME
        assert doc.mime_type == _MIME
        assert doc.chunk_count == 3
        assert doc.created_at == doc.updated_at
        assert doc.created_at.tzinfo is UTC

    def test_create_generates_a_unique_id(self) -> None:
        doc_a = Document.create(owner=_OWNER, name=_NAME, mime_type=_MIME, chunk_count=1)
        doc_b = Document.create(owner=_OWNER, name=_NAME, mime_type=_MIME, chunk_count=1)
        assert doc_a.id != doc_b.id

    def test_create_rejects_zero_chunks(self) -> None:
        # Should be structurally unreachable — empty documents are rejected
        # earlier, at the parsing stage (US-R01: MIN_EXTRACTED_TEXT_CHARS).
        # Hitting this is an internal defect, not a client mistake.
        with pytest.raises(ValueError, match="at least 1"):
            Document.create(owner=_OWNER, name=_NAME, mime_type=_MIME, chunk_count=0)

    def test_create_rejects_too_many_chunks(self) -> None:
        # Reachable in practice: only knowable after chunking completes
        # (US-R01: 422 ERR_TOO_MANY_CHUNKS) — a real client-triggerable path.
        with pytest.raises(DomainValidationError, match="chunk") as exc:
            Document.create(
                owner=_OWNER,
                name=_NAME,
                mime_type=_MIME,
                chunk_count=MAX_CHUNKS_PER_DOCUMENT + 1,
            )
        assert exc.value.field == "chunk_count"

    def test_from_repo_reconstructs_verbatim(self) -> None:
        doc_id = DocumentId.new()
        created = datetime(2026, 1, 1, tzinfo=UTC)
        updated = datetime(2026, 1, 2, tzinfo=UTC)
        doc = Document.from_repo(
            id=doc_id,
            owner=_OWNER,
            name=_NAME,
            mime_type=_MIME,
            chunk_count=5,
            created_at=created,
            updated_at=updated,
        )
        assert doc.id == doc_id
        assert doc.created_at == created
        assert doc.updated_at == updated

    def test_rename_updates_name_and_bumps_updated_at(self) -> None:
        doc = Document.create(owner=_OWNER, name=_NAME, mime_type=_MIME, chunk_count=1)
        original_updated_at = doc.updated_at
        new_name = DocumentName("Renamed.pdf")
        doc.rename(new_name)
        assert doc.name == new_name
        assert doc.updated_at >= original_updated_at

    def test_replace_content_updates_fields_and_bumps_updated_at(self) -> None:
        doc = Document.create(owner=_OWNER, name=_NAME, mime_type=_MIME, chunk_count=1)
        original_updated_at = doc.updated_at
        new_mime = MimeType("text/plain")
        doc.replace_content(mime_type=new_mime, chunk_count=7)
        assert doc.mime_type == new_mime
        assert doc.chunk_count == 7
        assert doc.updated_at >= original_updated_at

    def test_equal_when_same_id_regardless_of_other_fields(self) -> None:
        doc_id = DocumentId.new()
        now = datetime(2026, 1, 1, tzinfo=UTC)
        a = Document.from_repo(
            id=doc_id,
            owner=_OWNER,
            name=_NAME,
            mime_type=_MIME,
            chunk_count=1,
            created_at=now,
            updated_at=now,
        )
        b = Document.from_repo(
            id=doc_id,
            owner=OwnerSubject("someone-else"),
            name=DocumentName("Other.pdf"),
            mime_type=MimeType("text/plain"),
            chunk_count=99,
            created_at=now,
            updated_at=now,
        )
        assert a == b

    def test_not_equal_when_different_id_or_other_type(self) -> None:
        doc = Document.create(owner=_OWNER, name=_NAME, mime_type=_MIME, chunk_count=1)
        other_doc = Document.create(owner=_OWNER, name=_NAME, mime_type=_MIME, chunk_count=1)
        assert doc != other_doc
        assert doc != object()

    def test_hashable_by_id(self) -> None:
        doc_id = DocumentId.new()
        now = datetime(2026, 1, 1, tzinfo=UTC)
        a = Document.from_repo(
            id=doc_id,
            owner=_OWNER,
            name=_NAME,
            mime_type=_MIME,
            chunk_count=1,
            created_at=now,
            updated_at=now,
        )
        b = Document.from_repo(
            id=doc_id,
            owner=_OWNER,
            name=_NAME,
            mime_type=_MIME,
            chunk_count=1,
            created_at=now,
            updated_at=now,
        )
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
