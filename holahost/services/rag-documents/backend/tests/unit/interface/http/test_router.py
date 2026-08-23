"""Unit tests for the document routes (UC-R1..UC-R5, §7.1-§7.4), via TestClient with
every port dependency overridden by a fake — no real DB, model, or JWT involved.
"""

from fastapi import FastAPI
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

from interface.http.api_base import API_BASE_URL
from interface.http.dependencies import (
    get_chunker,
    get_documents_repo_factory,
    get_embedding_model,
    get_parser,
    get_uow,
    get_vector_search_factory,
)
from interface.http.errors import register_error_handlers
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
    register_error_handlers(app)
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
        # Missing entirely -> RequestValidationError -> 422 (FastAPI's own default,
        # matching RFC 4918: syntax fine, content doesn't satisfy what's needed).
        # An empty *value* for `name` goes through a different path
        # (application-layer InvalidPayloadError) but lands on the same 422 now too
        # — unified, see clarifications.md.
        client = TestClient(_build_app())

        response = client.post(
            "/api/rag-documents/documents",
            files={"file": ("guide.txt", b"hello world", "text/plain")},
            headers=_HEADERS,
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ERR_INVALID_PAYLOAD"


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
