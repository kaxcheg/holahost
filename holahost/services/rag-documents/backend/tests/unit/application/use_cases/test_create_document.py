"""Tests for CreateDocumentUseCase (UC-R1)."""

from __future__ import annotations

import pytest
from tests._support.builders import make_embedding
from tests._support.fakes import (
    FakeChunksRepo,
    FakeDocumentsRepo,
    FakeEmbeddingModel,
    FakeFileParser,
    FakeTextChunker,
    FakeUnitOfWork,
)

from application.dto.documents import CreateDocumentCmd
from application.exceptions import (
    DocumentParseError,
    EmptyDocumentError,
    InvalidPayloadError,
    ParsedTextTooLargeError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
    UploadTooLargeError,
)
from application.limits import MAX_PARSED_TEXT_LENGTH, MAX_UPLOAD_SIZE
from application.ports.ingestion import TextFragment
from application.use_cases.create_document import CreateDocumentUseCase
from domain.entities.document import MAX_CHUNKS_PER_DOCUMENT
from domain.value_objects.page_number import PageNumber

_CMD = CreateDocumentCmd(
    owner="user-123", name="Guidebook.pdf", content=b"pdf-bytes", mime_type="application/pdf"
)


def _uc(
    *,
    fragments: list[TextFragment] | None = None,
    chunks: list[TextFragment] | None = None,
    parser_error: Exception | None = None,
    documents_repo: FakeDocumentsRepo | None = None,
    chunks_repo: FakeChunksRepo | None = None,
) -> CreateDocumentUseCase:
    default_fragment = [TextFragment(text="x" * 250, page=PageNumber(1))]
    return CreateDocumentUseCase(
        parser=FakeFileParser(
            fragments if fragments is not None else default_fragment, error=parser_error
        ),
        chunker=FakeTextChunker(chunks),
        embedder=FakeEmbeddingModel(make_embedding()),
        documents_repo=documents_repo or FakeDocumentsRepo(),
        chunks_repo=chunks_repo or FakeChunksRepo(),
        uow=FakeUnitOfWork(),
    )


class TestCreateDocumentUseCase:
    def test_creates_document_and_chunks_atomically(self) -> None:
        documents_repo = FakeDocumentsRepo()
        chunks_repo = FakeChunksRepo()
        view = _uc(documents_repo=documents_repo, chunks_repo=chunks_repo).execute(_CMD)

        assert len(documents_repo.added) == 1
        assert len(chunks_repo.added) == 1
        assert view.name == "Guidebook.pdf"
        assert view.chunk_count == 1
        assert view.created_at == view.updated_at

    def test_rejects_unsupported_mime_type(self) -> None:
        cmd = CreateDocumentCmd(owner="u", name="n", content=b"x", mime_type="image/png")
        with pytest.raises(UnsupportedMediaTypeError):
            _uc().execute(cmd)

    def test_rejects_empty_name(self) -> None:
        cmd = CreateDocumentCmd(owner="u", name="   ", content=b"x", mime_type="application/pdf")
        with pytest.raises(InvalidPayloadError) as exc:
            _uc().execute(cmd)
        assert exc.value.field == "name"

    def test_rejects_upload_over_max_size(self) -> None:
        cmd = CreateDocumentCmd(
            owner="u", name="n", content=b"x" * (MAX_UPLOAD_SIZE + 1), mime_type="application/pdf"
        )
        with pytest.raises(UploadTooLargeError):
            _uc().execute(cmd)

    def test_rejects_too_little_extracted_text(self) -> None:
        fragments = [TextFragment(text="short", page=PageNumber(1))]
        with pytest.raises(EmptyDocumentError):
            _uc(fragments=fragments).execute(_CMD)

    def test_rejects_parsed_text_over_max_length(self) -> None:
        fragments = [TextFragment(text="x" * (MAX_PARSED_TEXT_LENGTH + 1), page=PageNumber(1))]
        with pytest.raises(ParsedTextTooLargeError):
            _uc(fragments=fragments).execute(_CMD)

    def test_rejects_too_many_chunks(self) -> None:
        chunks = [
            TextFragment(text="x" * 250, page=PageNumber(1))
            for _ in range(MAX_CHUNKS_PER_DOCUMENT + 1)
        ]
        with pytest.raises(TooManyChunksError):
            _uc(chunks=chunks).execute(_CMD)

    def test_parser_error_propagates_directly(self) -> None:
        with pytest.raises(DocumentParseError):
            _uc(parser_error=DocumentParseError()).execute(_CMD)

    def test_nothing_persisted_on_pipeline_failure(self) -> None:
        documents_repo = FakeDocumentsRepo()
        chunks_repo = FakeChunksRepo()
        cmd = CreateDocumentCmd(owner="u", name="n", content=b"x", mime_type="image/png")
        with pytest.raises(UnsupportedMediaTypeError):
            _uc(documents_repo=documents_repo, chunks_repo=chunks_repo).execute(cmd)
        assert documents_repo.added == []
        assert chunks_repo.added == []
