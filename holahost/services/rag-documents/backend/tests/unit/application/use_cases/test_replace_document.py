"""Tests for ReplaceDocumentUseCase."""

from __future__ import annotations

import uuid

import pytest
from tests._support.builders import make_document, make_embedding, make_text_fragment
from tests._support.fakes import (
    FakeDocumentsRepo,
    FakeEmbeddingModel,
    FakeFileParser,
    FakeTextChunker,
    FakeUnitOfWork,
)

from application.dto.documents import ReplaceDocumentCmd
from application.exceptions import (
    EmptyDocumentError,
    InvalidPayloadError,
    NotFoundError,
    ParsedTextTooLargeError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
    UploadTooLargeError,
)
from application.limits import MAX_PARSED_TEXT_LENGTH, MAX_UPLOAD_SIZE
from application.ports.exceptions import ConcurrentUpdateError
from application.ports.ingestion import TextFragment
from application.use_cases.replace_document import ReplaceDocumentUseCase
from domain.entities.document import MAX_CHUNKS_PER_DOCUMENT, Document
from domain.value_objects.document_id import DocumentId
from domain.value_objects.page_number import PageNumber

_FRAGMENT = TextFragment(text="x" * 250, page=PageNumber(1))


def _uc(
    documents_repo: FakeDocumentsRepo,
    *,
    fragments: list[TextFragment] | None = None,
    chunks: list[TextFragment] | None = None,
) -> ReplaceDocumentUseCase:
    return ReplaceDocumentUseCase(
        parser=FakeFileParser(fragments if fragments is not None else [_FRAGMENT]),
        chunker=FakeTextChunker(chunks),
        embedder=FakeEmbeddingModel(make_embedding()),
        documents_repo_factory=documents_repo,
        uow=FakeUnitOfWork(),
    )


class TestReplaceDocumentUseCase:
    def test_replaces_content_keeping_document_id(self) -> None:
        existing = make_document(owner="user-123", chunk_count=1)
        documents_repo = FakeDocumentsRepo([existing])
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id),
            owner="user-123",
            content=b"x",
            mime_type="application/pdf",
        )

        view = _uc(documents_repo).execute(cmd)

        assert view.document_id == str(existing.id)
        assert len(documents_repo.updated) == 1
        updated_chunks = documents_repo.updated[0].chunks
        assert updated_chunks is not None
        assert len(updated_chunks) == 1

    def test_replace_of_missing_document_raises_not_found(self) -> None:
        cmd = ReplaceDocumentCmd(
            document_id=str(uuid.uuid4()),
            owner="user-123",
            content=b"x",
            mime_type="application/pdf",
        )
        with pytest.raises(NotFoundError):
            _uc(FakeDocumentsRepo()).execute(cmd)

    def test_replace_of_other_owners_document_raises_not_found(self) -> None:
        existing = make_document(owner="someone-else", chunk_count=1)
        documents_repo = FakeDocumentsRepo([existing])
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id),
            owner="user-123",
            content=b"x",
            mime_type="application/pdf",
        )
        with pytest.raises(NotFoundError):
            _uc(documents_repo).execute(cmd)

    def test_pipeline_failure_leaves_previous_version_intact(self) -> None:
        existing = make_document(owner="user-123", chunk_count=1)
        documents_repo = FakeDocumentsRepo([existing])
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id), owner="user-123", content=b"x", mime_type="image/png"
        )
        with pytest.raises(UnsupportedMediaTypeError):
            _uc(documents_repo).execute(cmd)
        assert documents_repo.updated == []

    def test_rejects_upload_over_max_size(self) -> None:
        existing = make_document(owner="user-123", chunk_count=1)
        documents_repo = FakeDocumentsRepo([existing])
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id),
            owner="user-123",
            content=b"x" * (MAX_UPLOAD_SIZE + 1),
            mime_type="application/pdf",
        )
        with pytest.raises(UploadTooLargeError):
            _uc(documents_repo).execute(cmd)

    def test_rejects_too_little_extracted_text(self) -> None:
        existing = make_document(owner="user-123", chunk_count=1)
        documents_repo = FakeDocumentsRepo([existing])
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id),
            owner="user-123",
            content=b"x",
            mime_type="application/pdf",
        )
        fragments = [TextFragment(text="short", page=PageNumber(1))]
        with pytest.raises(EmptyDocumentError):
            _uc(documents_repo, fragments=fragments).execute(cmd)

    def test_rejects_parsed_text_over_max_length(self) -> None:
        existing = make_document(owner="user-123", chunk_count=1)
        documents_repo = FakeDocumentsRepo([existing])
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id),
            owner="user-123",
            content=b"x",
            mime_type="application/pdf",
        )
        fragments = [TextFragment(text="x" * (MAX_PARSED_TEXT_LENGTH + 1), page=PageNumber(1))]
        with pytest.raises(ParsedTextTooLargeError):
            _uc(documents_repo, fragments=fragments).execute(cmd)

    def test_rejects_too_many_chunks(self) -> None:
        existing = make_document(owner="user-123", chunk_count=1)
        documents_repo = FakeDocumentsRepo([existing])
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id),
            owner="user-123",
            content=b"x",
            mime_type="application/pdf",
        )
        chunks = [
            TextFragment(text="x" * 250, page=PageNumber(1))
            for _ in range(MAX_CHUNKS_PER_DOCUMENT + 1)
        ]
        with pytest.raises(TooManyChunksError):
            _uc(documents_repo, chunks=chunks).execute(cmd)

    def test_rejects_invalid_new_name(self) -> None:
        existing = make_document(owner="user-123", chunk_count=1)
        documents_repo = FakeDocumentsRepo([existing])
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id),
            owner="user-123",
            content=b"x",
            mime_type="application/pdf",
            name="   ",
        )
        with pytest.raises(InvalidPayloadError) as exc:
            _uc(documents_repo).execute(cmd)
        assert exc.value.field == "name"

    def test_retries_once_on_concurrent_update_then_succeeds(self) -> None:
        existing = make_document(owner="user-123", chunk_count=1)

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
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id),
            owner="user-123",
            content=b"x",
            mime_type="application/pdf",
        )
        view = _uc(documents_repo).execute(cmd)
        assert view.document_id == str(existing.id)

    def test_gives_up_after_two_retries(self) -> None:
        existing = make_document(owner="user-123", chunk_count=1)

        class _AlwaysConflictingDocumentsRepo(FakeDocumentsRepo):
            def _get_impl(self, document_id: DocumentId, *, lock: bool) -> Document | None:
                if lock:
                    raise ConcurrentUpdateError
                return super()._get_impl(document_id, lock=lock)

        documents_repo = _AlwaysConflictingDocumentsRepo([existing])
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id),
            owner="user-123",
            content=b"x",
            mime_type="application/pdf",
        )
        with pytest.raises(ConcurrentUpdateError):
            _uc(documents_repo).execute(cmd)

    def test_name_is_optional_and_preserved_when_not_given(self) -> None:
        existing = make_document(owner="user-123", name="Original.pdf", chunk_count=1)
        documents_repo = FakeDocumentsRepo([existing])
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id),
            owner="user-123",
            content=b"x",
            mime_type="application/pdf",
            name=None,
        )
        view = _uc(documents_repo).execute(cmd)
        assert view.name == "Original.pdf"

    def test_locked_recheck_catches_concurrent_delete(self) -> None:
        existing = make_document(owner="user-123", chunk_count=1)

        class _DeletedBeforeLockDocumentsRepo(FakeDocumentsRepo):
            def _get_impl(self, document_id: DocumentId, *, lock: bool) -> Document | None:
                if lock:
                    return None
                return super()._get_impl(document_id, lock=lock)

        documents_repo = _DeletedBeforeLockDocumentsRepo([existing])
        cmd = ReplaceDocumentCmd(
            document_id=str(existing.id),
            owner="user-123",
            content=b"x",
            mime_type="application/pdf",
        )
        with pytest.raises(NotFoundError):
            _uc(documents_repo).execute(cmd)


class TestInvalidNameIsRejectedBeforeAnyWork:
    """An unacceptable name is a property of the request, knowable before the pipeline.

    Checked after parse/chunk/embed, it would cost the service's most expensive path to
    produce a 422 the first microsecond could have. Asserting the *ports were never
    called* is what pins the order — asserting only the exception passes either way.
    """

    def test_pipeline_ports_are_never_touched(self) -> None:
        existing = make_document(owner="user-123")
        parser = FakeFileParser(fragments=[make_text_fragment(text="x" * 250)])
        chunker = FakeTextChunker()
        embedder = FakeEmbeddingModel(make_embedding())
        use_case = ReplaceDocumentUseCase(
            documents_repo_factory=FakeDocumentsRepo([existing]),
            parser=parser,
            chunker=chunker,
            embedder=embedder,
            uow=FakeUnitOfWork(),
        )

        with pytest.raises(InvalidPayloadError) as exc:
            use_case.execute(
                ReplaceDocumentCmd(
                    document_id=str(existing.id),
                    owner="user-123",
                    name="   ",  # blank after strip — rejected by DocumentName
                    content=b"x" * 100,
                    mime_type="text/plain",
                )
            )

        assert exc.value.field == "name"
        assert parser.calls == 0
        assert chunker.calls == 0
        assert embedder.calls == 0
