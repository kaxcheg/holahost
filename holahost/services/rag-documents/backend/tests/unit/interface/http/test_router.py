"""Unit tests for the document routes (UC-R1..UC-R5, §7.1-§7.4), via TestClient with
every port dependency overridden by a fake — no real DB, model, or JWT involved.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from holahost_auth import AuthenticationError, TokenContext
from tests._support.builders import make_document, make_embedding, make_text_fragment
from tests._support.fakes import (
    FakeDocumentsRepo,
    FakeEmbeddingModel,
    FakeFileParser,
    FakeRateLimiter,
    FakeTextChunker,
    FakeUnitOfWork,
    FakeVectorSearch,
)

from interface.http.dependencies import (
    get_auth,
    get_chunker,
    get_current_token,
    get_documents_repo_factory,
    get_embedding_model,
    get_parser,
    get_rate_limiter,
    get_uow,
    get_vector_search_factory,
)
from interface.http.errors import register_error_handlers
from interface.http.middleware import RequestIdMiddleware
from interface.http.router import router as documents_router

# Matches FakeDocumentsRepo/FakeVectorSearch's own default owner ("user-123") so tests
# that don't explicitly pass documents/owner still resolve against the same subject.
_TOKEN = TokenContext(subject="user-123", client_id="cli-1", roles=(), act=None)
_LONG_ENOUGH_TEXT = "x" * 250  # > MIN_EXTRACTED_TEXT_CHARS (200), so create doesn't 422
_HEADERS = {"X-Request-ID": "test-request-id"}  # required on every route but /health


def _build_app(*, rate_limiter: FakeRateLimiter | None = None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(documents_router)

    fake_repo = FakeDocumentsRepo()
    fake_vector_search = FakeVectorSearch()
    app.dependency_overrides[get_current_token] = lambda: _TOKEN
    app.dependency_overrides[get_uow] = lambda: FakeUnitOfWork()
    app.dependency_overrides[get_documents_repo_factory] = lambda: fake_repo
    app.dependency_overrides[get_vector_search_factory] = lambda: fake_vector_search
    app.dependency_overrides[get_parser] = lambda: FakeFileParser(
        fragments=[make_text_fragment(text=_LONG_ENOUGH_TEXT)]
    )
    app.dependency_overrides[get_chunker] = lambda: FakeTextChunker()
    app.dependency_overrides[get_embedding_model] = lambda: FakeEmbeddingModel(make_embedding())
    app.dependency_overrides[get_rate_limiter] = lambda: (rate_limiter or FakeRateLimiter())
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

    def test_rate_limited_returns_429(self) -> None:
        client = TestClient(_build_app(rate_limiter=FakeRateLimiter(should_raise=True)))

        response = client.post(
            "/api/rag-documents/documents",
            files={"file": ("guide.txt", b"hello world", "text/plain")},
            data={"name": "Guidebook"},
            headers=_HEADERS,
        )

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "30"

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

    def test_no_token_returns_401_before_body_is_validated(self) -> None:
        # auth-before-schema-validation ordering (§8.1 step 2 before step 4) — build a
        # fresh app WITHOUT overriding get_current_token (so get_current_token's real
        # body runs), override only get_auth with a fake that always rejects (mirrors
        # holahost-auth's own AuthenticationError, without needing real Settings/JWKS),
        # and omit the `name` field too, to see which failure wins.
        # X-Request-ID is present here — this test isolates auth-vs-body ordering, not
        # the request-id gate (see TestRequestIdRequired for that).
        app = _build_app()
        del app.dependency_overrides[get_current_token]
        app.dependency_overrides[get_auth] = lambda: _AlwaysRejectingAuth()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/rag-documents/documents",
            files={"file": ("guide.txt", b"hello world", "text/plain")},
            headers=_HEADERS,
            # `name` deliberately omitted too
        )

        assert response.status_code == 401


class TestRequestIdRequired:
    def test_missing_request_id_returns_422(self) -> None:
        # get_current_token's own override (the norm for most tests here) would
        # bypass its require_request_id sub-dependency entirely — deleting it so the
        # real body runs is what actually exercises the check. get_auth is swapped
        # for a fake that would succeed, isolating "request-id missing" from auth.
        app = _build_app()
        del app.dependency_overrides[get_current_token]
        app.dependency_overrides[get_auth] = lambda: _AlwaysAcceptingAuth()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/rag-documents/documents",
            files={"file": ("guide.txt", b"hello world", "text/plain")},
            data={"name": "Guidebook"},
            # no X-Request-ID header at all
        )

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "ERR_INVALID_PAYLOAD"
        assert body["error"]["details"] == {"field": "X-Request-ID"}

    def test_request_id_check_runs_before_auth(self) -> None:
        # Same shape as test_no_token_returns_401_before_body_is_validated, but with
        # X-Request-ID omitted this time and auth set to always-reject — proves the
        # request-id gate wins over auth (422, not 401), not just over body validation.
        app = _build_app()
        del app.dependency_overrides[get_current_token]
        app.dependency_overrides[get_auth] = lambda: _AlwaysRejectingAuth()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/rag-documents/documents",
            files={"file": ("guide.txt", b"hello world", "text/plain")},
            data={"name": "Guidebook"},
            # no X-Request-ID header
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ERR_INVALID_PAYLOAD"


class _AlwaysRejectingAuth:
    """Fake `HolahostAuth` — matches its `__call__(authorization) -> TokenContext`
    shape, always raises the same `AuthenticationError` the real library raises on
    any per-request validation failure (it raises this directly, not
    `HTTPException` — `errors.py` owns the type -> status mapping)."""

    def __call__(self, authorization: str | None) -> TokenContext:
        raise AuthenticationError("always rejects")


class _AlwaysAcceptingAuth:
    """Fake `HolahostAuth` that always succeeds — used where a test needs
    `get_current_token`'s real body to run (so its sub-dependencies actually
    execute) without also exercising/failing the auth path itself."""

    def __call__(self, authorization: str | None) -> TokenContext:
        return _TOKEN


class TestSearchDocument:
    def test_not_found_returns_404(self) -> None:
        client = TestClient(_build_app())

        response = client.post(
            "/api/rag-documents/documents/8f14e45f-ceea-467a-9f0a-1c2d3e4f5a6b/search",
            json={"query": "check-in time"},
            headers=_HEADERS,
        )

        assert response.status_code == 404


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
