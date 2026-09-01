"""Unit tests for the document routes (UC-R1..UC-R5, §7.1-§7.4), via TestClient with
every port dependency overridden by a fake — no real DB, model, or JWT involved.
"""

from tempfile import SpooledTemporaryFile
from typing import BinaryIO, cast

from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient
from holahost_auth import TokenContext, current_token
from holahost_http import RequestIdMiddleware
from starlette.middleware import Middleware
from tests._support.builders import make_document, make_embedding, make_text_fragment
from tests._support.fakes import (
    FakeDocumentsRepo,
    FakeEmbeddingModel,
    FakeFileParser,
    FakeTextChunker,
    FakeUnitOfWork,
    FakeVectorSearch,
)
from tests._support.http import register_test_handlers

from interface.http.api_base import API_BASE_URL
from interface.http.dependencies import (
    get_chunker,
    get_documents_repo_factory,
    get_embedding_model,
    get_parser,
    get_uow,
    get_vector_search_factory,
)
from interface.http.router import _read_upload
from interface.http.router import router as documents_router

# Matches FakeDocumentsRepo/FakeVectorSearch's own default owner ("user-123") so tests
# that don't explicitly pass documents/owner still resolve against the same subject.
_TOKEN = TokenContext(subject="user-123", client_id="cli-1", roles=(), act=None)
_LONG_ENOUGH_TEXT = "x" * 250  # > MIN_EXTRACTED_TEXT_CHARS (200), so create doesn't 422
_HEADERS = {"X-Request-ID": "test-request-id"}  # required on every route but /health


def _build_app() -> FastAPI:
    """Routes only. Authentication, rate limiting and the request-id requirement run
    ahead of routing now and are covered in `test_middleware.py`; here the token is
    injected by overriding `current_token`, which is all a route sees of any of it."""
    app = FastAPI(middleware=[Middleware(RequestIdMiddleware)])
    register_test_handlers(app)
    app.include_router(documents_router, prefix=API_BASE_URL)

    fake_repo = FakeDocumentsRepo()
    fake_vector_search = FakeVectorSearch()
    app.dependency_overrides[current_token] = lambda: _TOKEN
    app.dependency_overrides[get_uow] = lambda: FakeUnitOfWork()
    app.dependency_overrides[get_documents_repo_factory] = lambda: fake_repo
    app.dependency_overrides[get_vector_search_factory] = lambda: fake_vector_search
    app.dependency_overrides[get_parser] = lambda: FakeFileParser(
        fragments=[make_text_fragment(text=_LONG_ENOUGH_TEXT)]
    )
    app.dependency_overrides[get_chunker] = lambda: FakeTextChunker()
    app.dependency_overrides[get_embedding_model] = lambda: FakeEmbeddingModel(make_embedding())
    return app


class TestCreateDocument:
    def test_happy_path_returns_201(self) -> None:
        client = TestClient(_build_app())

        response = client.post(
            "/api/rag-documents/documents",
            files={"file": ("guide.txt", b"hello world, this is guidance content", "text/plain")},
            data={"name": "Guidebook"},
            headers=_HEADERS,
        )

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Guidebook"
        assert "document_id" in body

    def test_missing_name_field_returns_422(self) -> None:
        # Missing entirely -> RequestValidationError -> 422. An empty *value* for `name`
        # takes a different path (application-layer InvalidPayloadError) and lands on the
        # same 422.
        client = TestClient(_build_app())

        response = client.post(
            "/api/rag-documents/documents",
            files={"file": ("guide.txt", b"hello world", "text/plain")},
            headers=_HEADERS,
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "InvalidPayloadError"


class TestGetDocument:
    def test_happy_path_returns_200(self) -> None:
        app = _build_app()
        document = make_document()  # default owner "user-123", matching _TOKEN.subject
        app.dependency_overrides[get_documents_repo_factory] = lambda: FakeDocumentsRepo(
            documents=[document]
        )
        client = TestClient(app)

        response = client.get(f"/api/rag-documents/documents/{document.id}", headers=_HEADERS)

        assert response.status_code == 200


class TestDeleteDocument:
    def test_not_found_returns_404(self) -> None:
        client = TestClient(_build_app())

        response = client.delete(
            "/api/rag-documents/documents/8f14e45f-ceea-467a-9f0a-1c2d3e4f5a6b",
            headers=_HEADERS,
        )

        assert response.status_code == 404


class TestReplaceDocument:
    def test_not_found_returns_404(self) -> None:
        client = TestClient(_build_app())

        response = client.put(
            "/api/rag-documents/documents/8f14e45f-ceea-467a-9f0a-1c2d3e4f5a6b",
            files={"file": ("guide.txt", b"hello world", "text/plain")},
            headers=_HEADERS,
        )

        assert response.status_code == 404


class TestReadUpload:
    """§3.8 holds the whole upload in memory, so the endpoint must not keep two copies
    of it — see `_read_upload`.

    The `cast`: `SpooledTemporaryFile` is exactly what Starlette's own multipart parser
    hands `UploadFile`, but typeshed does not declare it as a `BinaryIO`, so the real
    production shape needs spelling out for mypy rather than substituting a stand-in
    that would not exercise the close behaviour under test.
    """

    def test_returns_the_bytes_and_releases_the_parsers_copy(self) -> None:
        with SpooledTemporaryFile(max_size=1024 * 1024) as spool:
            spool.write(b"guidebook bytes")
            spool.seek(0)

            content = _read_upload(UploadFile(file=cast(BinaryIO, spool), filename="guide.txt"))

            assert content == b"guidebook bytes"
            assert spool.closed

    def test_the_frameworks_own_second_close_is_harmless(self) -> None:
        # FastAPI closes the form's files again when the request ends; that must stay a
        # no-op rather than an error raised after the response was already produced.
        with SpooledTemporaryFile(max_size=1024 * 1024) as spool:
            spool.write(b"x")
            spool.seek(0)
            upload = UploadFile(file=cast(BinaryIO, spool), filename="guide.txt")

            _read_upload(upload)
            upload.file.close()

            assert spool.closed
