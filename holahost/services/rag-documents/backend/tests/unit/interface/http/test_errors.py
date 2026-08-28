"""Unit tests for the exception -> HTTP envelope handler (ticket R-22, spec §7.6/§8.6).

Covers what routes raise. Rate limiting, body size and the request-id requirement are
refused before routing now and never reach these handlers — see `test_middleware.py`.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from holahost_http import RequestIdMiddleware
from pydantic import BaseModel

from application.exceptions import (
    ApplicationError,
    NotFoundError,
    TooManyChunksError,
    UploadTooLargeError,
)
from config.logging import configure_logging
from domain.exceptions import DomainValidationError
from interface.http.errors import register_error_handlers

_INTERNAL_INVARIANT_MESSAGE = "Embedding must be L2-normalized (got norm=0.9993)"


class _DerivedNotFoundError(NotFoundError):
    """A subclass nobody put in the table — it must still map to its base's status."""


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

    @app.get("/derived-not-found")
    def derived_not_found() -> None:
        raise _DerivedNotFoundError

    @app.get("/unmapped")
    def unmapped() -> None:
        # No production code constructs one; the handler must still not leak it.
        raise ApplicationError(_INTERNAL_INVARIANT_MESSAGE)

    @app.get("/domain-invariant")
    def domain_invariant() -> None:
        # What a VO/entity raises when an invariant no caller could have violated
        # is broken — `field` unset, so nothing upstream translated it.
        raise DomainValidationError(_INTERNAL_INVARIANT_MESSAGE)

    @app.get("/untranslated-field-error")
    def untranslated_field_error() -> None:
        # The other half: client-fixable, but the use case forgot to translate it.
        raise DomainValidationError("DocumentName must not be empty", field="name")

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
        assert body["error"]["code"] == "UploadTooLargeError"
        assert body["error"]["details"] == {"limit": 100, "actual": 200}

    def test_too_many_chunks_maps_to_422_despite_same_code_family(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/too-many-chunks")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "TooManyChunksError"

    def test_not_found_maps_to_404_with_no_details(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/not-found")

        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "NotFoundError",
            "message": "document not found",
            "details": {},
        }

    def test_an_unpublished_subclass_is_answered_as_its_published_ancestor(self) -> None:
        # The lookup walks the MRO, and takes the *identity* from the matched ancestor:
        # a subclass has no entry in docs/openapi.json, so answering with its own name
        # would put an identity on the wire the published schema does not describe.
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/derived-not-found")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NotFoundError"


class TestUnmappedApplicationErrorIsInternal:
    """§7.6/US-R09: a 500 body carries no internal detail; the reason goes to the log."""

    def test_body_carries_no_internal_detail(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/unmapped")

        assert response.status_code == 500
        body = response.json()
        assert body["error"] == {
            "code": "InternalError",
            "message": "internal error",
            "details": {},
        }
        assert "norm=" not in response.text

    def test_reason_reaches_the_log(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The body carries nothing, so this line is the only place the cause survives.
        configure_logging()
        client = TestClient(_build_app(), raise_server_exceptions=False)

        client.get("/unmapped")

        assert _INTERNAL_INVARIANT_MESSAGE in capsys.readouterr().out


class TestDomainValidationErrorIsInternal:
    """An untranslated domain invariant violation is a defect — see
    `handle_domain_validation_error`."""

    def test_invariant_violation_maps_to_500_without_leaking(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/domain-invariant")

        assert response.status_code == 500
        body = response.json()
        assert body["error"] == {
            "code": "InternalError",
            "message": "internal error",
            "details": {},
        }
        assert "norm=" not in response.text

    def test_reason_reaches_the_log(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging()
        client = TestClient(_build_app(), raise_server_exceptions=False)

        client.get("/domain-invariant")

        assert _INTERNAL_INVARIANT_MESSAGE in capsys.readouterr().out

    def test_an_untranslated_field_error_is_also_500_not_a_guessed_4xx(self) -> None:
        # A `field`-carrying one that reached this layer means the use case that owed it
        # a §7.6 error did not produce one. That is a defect, not a client mistake, and
        # the handler must not invent a 422 out of the field name.
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/untranslated-field-error")

        assert response.status_code == 500
        assert response.json()["error"]["details"] == {}
        assert "name" not in response.json()["error"]["message"]


class TestValidationErrorMapping:
    def test_missing_body_field_maps_to_422_invalid_payload(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.post("/validated", json={})

        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "InvalidPayloadError"
        # US-R09: one code, one `details` field set — `limit` is present (null) rather
        # than absent, so a consumer reading it never has to know which raise site
        # answered.
        assert body["error"]["details"] == {"field": "x", "limit": None}


class TestUnexpectedExceptionMapping:
    def test_bare_exception_maps_to_500_with_no_leaked_detail(self) -> None:
        client = TestClient(_build_app(), raise_server_exceptions=False)

        response = client.get("/boom")

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "InternalError"
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


class TestLogLevelFollowsTheOutcome:
    """Regression: every event went out at `INFO`, including a 500 — while the formatter
    writes a `level` field on every line, so it promised a distinction it never made."""

    @staticmethod
    def _level(captured: str) -> str:
        # The handler writes one JSON object per line straight to stdout (§3.4); the
        # request under test is the last one.
        return str(json.loads(captured.strip().splitlines()[-1])["level"])

    def test_a_5xx_is_logged_at_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging()
        client = TestClient(_build_app(), raise_server_exceptions=False)

        client.get("/boom")

        assert self._level(capsys.readouterr().out) == "ERROR"

    def test_a_domain_invariant_violation_is_logged_at_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging()
        client = TestClient(_build_app(), raise_server_exceptions=False)

        client.get("/domain-invariant")

        assert self._level(capsys.readouterr().out) == "ERROR"

    def test_a_4xx_is_logged_at_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The caller's mistake, not the service's — visible, but not an alarm.
        configure_logging()
        client = TestClient(_build_app(), raise_server_exceptions=False)

        client.get("/not-found")

        assert self._level(capsys.readouterr().out) == "WARNING"

    def test_the_status_drives_it_not_the_outcome_string(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # `handle_http_exception` logs a bare numeric outcome ("404"), so the level has
        # to come from the status it is answering with, not from parsing that string.
        configure_logging()
        client = TestClient(_build_app(), raise_server_exceptions=False)

        client.get("/no-such-route")

        assert self._level(capsys.readouterr().out) == "WARNING"
