"""Unit tests for the exception -> HTTP envelope handler (ticket R-22, spec §7.6/§8.6).

Covers what routes raise. Rate limiting, body size and the request-id requirement are
refused before routing now and never reach these handlers — see `test_middleware.py`.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from holahost_http import RequestIdMiddleware
from pydantic import BaseModel

from application.exceptions import NotFoundError, TooManyChunksError, UploadTooLargeError
from interface.http.errors import register_error_handlers


class _Body(BaseModel):
    x: int


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    @app.get("/upload-too-large")
    def upload_too_large() -> None:
        raise UploadTooLargeError(limit=100, actual=200)

    @app.get("/too-many-chunks")
    def too_many_chunks() -> None:
        raise TooManyChunksError(limit=500, actual=600)

    @app.get("/not-found")
    def not_found() -> None:
        raise NotFoundError

    @app.post("/validated")
    def validated(body: _Body) -> None:
        return None

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("unexpected")

    return app


class TestApplicationErrorMapping:
    def test_upload_too_large_maps_to_413(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/upload-too-large")

        assert response.status_code == 413
        body = response.json()
        assert body["error"]["code"] == "ERR_PAYLOAD_TOO_LARGE"
        assert body["error"]["details"] == {"limit": 100, "actual": 200}

    def test_too_many_chunks_maps_to_422_despite_same_code_family(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/too-many-chunks")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ERR_TOO_MANY_CHUNKS"

    def test_not_found_maps_to_404_with_no_details(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/not-found")

        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "ERR_NOT_FOUND",
            "message": "document not found",
            "details": {},
        }


class TestValidationErrorMapping:
    def test_missing_body_field_maps_to_422_invalid_payload(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.post("/validated", json={})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ERR_INVALID_PAYLOAD"


class TestUnexpectedExceptionMapping:
    def test_bare_exception_maps_to_500_with_no_leaked_detail(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/boom")

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "ERR_INTERNAL"
        assert "RuntimeError" not in body["error"]["message"]
        assert "unexpected" not in str(body)

    def test_bare_exception_still_echoes_x_request_id(self) -> None:
        # Regression test: Starlette binds a bare `Exception` handler to the
        # outermost ServerErrorMiddleware, *outside* app.add_middleware()'d user
        # middleware — RequestIdMiddleware's own post-call_next header-echo code
        # never runs for this one path (every other handler in this file's app
        # IS caught by the inner ExceptionMiddleware and echoes correctly without
        # any special-casing; this is the one exception, literally).
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/boom", headers={"X-Request-ID": "req-500"})

        assert response.headers["X-Request-ID"] == "req-500"
