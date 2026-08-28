from datetime import UTC, datetime

import pytest
from tests._support.builders import make_chunk

from domain.entities.chunk import Chunk
from domain.entities.document import MAX_CHUNKS_PER_DOCUMENT, Document
from domain.exceptions import DomainValidationError
from domain.value_objects.document_id import DocumentId
from domain.value_objects.document_name import DocumentName
from domain.value_objects.mime_type import MimeType
from domain.value_objects.owner_subject import OwnerSubject

_OWNER = OwnerSubject("user-123")
_NAME = DocumentName("Guidebook.pdf")
_MIME = MimeType("application/pdf")


def _chunks(document_id: DocumentId, count: int = 1) -> list[Chunk]:
    return [make_chunk(document_id=document_id, index=i) for i in range(count)]


class TestDocument:
    def test_create_sets_fields_and_matching_timestamps(self) -> None:
        doc_id = DocumentId.new()
        doc = Document.create(
            id=doc_id, owner=_OWNER, name=_NAME, mime_type=_MIME, chunks=_chunks(doc_id, 3)
        )
        assert doc.id == doc_id
        assert doc.owner == _OWNER
        assert doc.name == _NAME
        assert doc.mime_type == _MIME
        assert doc.chunk_count == 3
        assert doc.chunks is not None
        assert len(doc.chunks) == 3
        assert doc.created_at == doc.updated_at
        assert doc.created_at.tzinfo is UTC

    def test_create_rejects_zero_chunks(self) -> None:
        # Should be structurally unreachable — empty documents are rejected
        # earlier, at the parsing stage (US-R01: MIN_EXTRACTED_TEXT_CHARS).
        # Hitting this is an internal defect, not a client mistake.
        with pytest.raises(ValueError, match="at least one chunk"):
            Document.create(
                id=DocumentId.new(), owner=_OWNER, name=_NAME, mime_type=_MIME, chunks=[]
            )

    def test_create_rejects_too_many_chunks(self) -> None:
        # Reachable in practice: only knowable after chunking completes
        # (US-R01: 422 TooManyChunksError) — a real client-triggerable path.
        doc_id = DocumentId.new()
        with pytest.raises(DomainValidationError, match="chunk") as exc:
            Document.create(
                id=doc_id,
                owner=_OWNER,
                name=_NAME,
                mime_type=_MIME,
                chunks=_chunks(doc_id, MAX_CHUNKS_PER_DOCUMENT + 1),
            )
        assert exc.value.field == "chunk_count"

    def test_create_rejects_chunk_belonging_to_another_document(self) -> None:
        # Internal defect: a caller passed chunks built for a different id.
        foreign_chunk = make_chunk(document_id=DocumentId.new())
        with pytest.raises(ValueError, match="belong to this document"):
            Document.create(
                id=DocumentId.new(),
                owner=_OWNER,
                name=_NAME,
                mime_type=_MIME,
                chunks=[foreign_chunk],
            )

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
        assert doc.chunks is None

    def test_rename_updates_name_and_bumps_updated_at(self) -> None:
        doc_id = DocumentId.new()
        doc = Document.create(
            id=doc_id, owner=_OWNER, name=_NAME, mime_type=_MIME, chunks=_chunks(doc_id)
        )
        original_updated_at = doc.updated_at
        new_name = DocumentName("Renamed.pdf")
        doc.rename(new_name)
        assert doc.name == new_name
        assert doc.updated_at >= original_updated_at

    def test_rename_does_not_touch_chunks(self) -> None:
        doc_id = DocumentId.new()
        chunks = _chunks(doc_id)
        doc = Document.create(id=doc_id, owner=_OWNER, name=_NAME, mime_type=_MIME, chunks=chunks)
        doc.rename(DocumentName("Renamed.pdf"))
        assert doc.chunks == chunks
        assert doc.chunk_count == 1

    def test_replace_content_updates_fields_and_bumps_updated_at(self) -> None:
        doc_id = DocumentId.new()
        doc = Document.create(
            id=doc_id, owner=_OWNER, name=_NAME, mime_type=_MIME, chunks=_chunks(doc_id)
        )
        original_updated_at = doc.updated_at
        new_mime = MimeType("text/plain")
        new_chunks = _chunks(doc_id, 7)
        doc.replace_content(mime_type=new_mime, chunks=new_chunks)
        assert doc.mime_type == new_mime
        assert doc.chunk_count == 7
        assert doc.chunks == new_chunks
        assert doc.updated_at >= original_updated_at

    def test_replace_content_rejects_chunk_belonging_to_another_document(self) -> None:
        doc_id = DocumentId.new()
        doc = Document.create(
            id=doc_id, owner=_OWNER, name=_NAME, mime_type=_MIME, chunks=_chunks(doc_id)
        )
        foreign_chunk = make_chunk(document_id=DocumentId.new())
        with pytest.raises(ValueError, match="belong to this document"):
            doc.replace_content(mime_type=_MIME, chunks=[foreign_chunk])

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
        doc_id_a = DocumentId.new()
        doc_id_b = DocumentId.new()
        doc = Document.create(
            id=doc_id_a, owner=_OWNER, name=_NAME, mime_type=_MIME, chunks=_chunks(doc_id_a)
        )
        other_doc = Document.create(
            id=doc_id_b, owner=_OWNER, name=_NAME, mime_type=_MIME, chunks=_chunks(doc_id_b)
        )
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
