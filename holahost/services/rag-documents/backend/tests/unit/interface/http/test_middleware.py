"""Unit tests for the X-Request-ID middleware (spec §3.1, §8.1 step 1)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from interface.http.middleware import RequestIdMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/probe")
    def probe() -> dict[str, str]:
        return {}

    return app


class TestRequestIdMiddleware:
    def test_echoes_incoming_request_id(self) -> None:
        client = TestClient(_build_app())

        response = client.get("/probe", headers={"X-Request-ID": "abc-123"})

        assert response.headers["X-Request-ID"] == "abc-123"

    def test_does_not_synthesize_a_missing_request_id(self) -> None:
        client = TestClient(_build_app())

        response = client.get("/probe")

        assert "X-Request-ID" not in response.headers
