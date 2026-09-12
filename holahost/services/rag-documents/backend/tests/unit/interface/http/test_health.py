"""Unit tests for GET /api/rag-documents/health."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from interface.http.api_base import API_BASE_URL
from interface.http.dependencies import get_embedding_model, get_engine
from interface.http.health import router as health_router

# Mounted the same way `create_app()` mounts it, under the service's own base path — so these
# tests exercise the real, gateway-reachable URL rather than a bare `/health` no deployment
# ever serves.
_HEALTH_URL = f"{API_BASE_URL}/health"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(health_router, prefix=API_BASE_URL)
    return app


class _FakeConnection:
    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _WorkingEngine:
    def connect(self) -> contextlib.AbstractContextManager[_FakeConnection]:
        @contextlib.contextmanager
        def _cm() -> Iterator[_FakeConnection]:
            yield _FakeConnection()

        return _cm()


class _BrokenEngine:
    def connect(self) -> contextlib.AbstractContextManager[_FakeConnection]:
        raise ConnectionError("db down")


class TestHealth:
    def test_ok_when_db_and_model_are_ready(self) -> None:
        app = _build_app()
        app.dependency_overrides[get_engine] = lambda: _WorkingEngine()
        app.dependency_overrides[get_embedding_model] = lambda: object()
        client = TestClient(app)

        response = client.get(_HEALTH_URL)

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_no_auth_header_required(self) -> None:
        app = _build_app()
        app.dependency_overrides[get_engine] = lambda: _WorkingEngine()
        app.dependency_overrides[get_embedding_model] = lambda: object()
        client = TestClient(app)

        response = client.get(_HEALTH_URL)  # no Authorization header at all

        assert response.status_code == 200

    def test_503_when_db_unavailable(self) -> None:
        app = _build_app()
        app.dependency_overrides[get_engine] = lambda: _BrokenEngine()
        app.dependency_overrides[get_embedding_model] = lambda: object()
        client = TestClient(app)

        response = client.get(_HEALTH_URL)

        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
