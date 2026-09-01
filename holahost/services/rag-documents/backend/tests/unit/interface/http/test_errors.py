"""This service's half of the exception -> envelope mapping (§7.6/§8.6).

The machinery is `holahost_http.register_error_handlers`' and is tested there: the MRO
walk, the closed vocabulary, the bare-`Exception` path and its header echo, the log level
following the status. What is left here is what this service decides — which errors it
publishes and with what status, and that its own untranslated domain-invariant violation
is answered `500` rather than reaching Starlette's re-raising handler.

Rate limiting, body size and the request-id requirement are refused before routing and
never reach these handlers — see `test_edge.py`.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from holahost_http import NotFoundError, RequestIdMiddleware
from tests._support.http import register_test_handlers

from application.exceptions import (
    ApplicationError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
    UploadTooLargeError,
)
from config.logging import configure_logging
from domain.exceptions import ChunkCountExceededError, DomainValidationError
from interface.http.errors import ERROR_CONTRACT

_INTERNAL_INVARIANT_MESSAGE = "Embedding must be L2-normalized (got norm=0.9993)"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_test_handlers(app)

    @app.get("/upload-too-large")
    def upload_too_large() -> None:
        raise UploadTooLargeError(limit=100, actual=200)

    @app.get("/unsupported-media-type")
    def unsupported_media_type() -> None:
        raise UnsupportedMediaTypeError(allowed=("application/pdf",))

    @app.get("/too-many-chunks")
    def too_many_chunks() -> None:
        raise TooManyChunksError(limit=500, actual=600)

    @app.get("/not-found")
    def not_found() -> None:
        raise NotFoundError

    @app.get("/unmapped")
    def unmapped() -> None:
        # No production code constructs one; the handler must still not leak it.
        raise ApplicationError(_INTERNAL_INVARIANT_MESSAGE)

    @app.get("/domain-invariant")
    def domain_invariant() -> None:
        # What a VO/entity raises when an invariant no caller could have violated is
        # broken — `field` unset, so nothing upstream translated it.
        raise DomainValidationError(_INTERNAL_INVARIANT_MESSAGE)

    @app.get("/untranslated-field-error")
    def untranslated_field_error() -> None:
        # The other half: client-fixable, but the use case forgot to translate it.
        raise DomainValidationError("DocumentName must not be empty", field="name")

    @app.get("/untranslated-chunk-count")
    def untranslated_chunk_count() -> None:
        # The subclass a use case is supposed to catch and turn into TooManyChunksError.
        raise ChunkCountExceededError(limit=500)

    return app


def _client() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


class TestTheContract:
    def test_every_published_error_answers_its_declared_status(self) -> None:
        """One assertion per row of `ERROR_CONTRACT` that a route here can raise —
        the point being that the table is what decides, so a changed number shows up
        as a changed test rather than a changed handler."""
        client = _client()

        for path, error in [
            ("/upload-too-large", UploadTooLargeError),
            ("/unsupported-media-type", UnsupportedMediaTypeError),
            ("/too-many-chunks", TooManyChunksError),
            ("/not-found", NotFoundError),
        ]:
            response = client.get(path)
            assert response.status_code == ERROR_CONTRACT[error], path
            assert response.json()["error"]["code"] == error.__name__, path

    def test_two_errors_may_share_a_status_and_stay_distinguishable(self) -> None:
        # `TooManyChunksError` and `ParsedTextTooLargeError` are both 422; the identity,
        # not the status, is what a consumer branches on.
        client = _client()

        assert client.get("/too-many-chunks").status_code == 422
        assert client.get("/too-many-chunks").json()["error"]["code"] == "TooManyChunksError"

    def test_details_reach_the_caller(self) -> None:
        response = _client().get("/upload-too-large")

        assert response.json()["error"]["details"] == {"limit": 100, "actual": 200}

    def test_an_error_this_service_never_published_is_internal(self) -> None:
        # §7.6/US-R09: a 500 body carries no internal detail; the reason goes to the log.
        response = _client().get("/unmapped")

        assert response.status_code == 500
        assert response.json()["error"] == {
            "code": "InternalError",
            "message": "internal error",
            "details": {},
        }
        assert "norm=" not in response.text


class TestDomainValidationErrorIsInternal:
    """This service's `silent_500_types` wiring. Both halves are a defect: an unset
    `field` is internal by definition, and a `field`-carrying one that got this far means
    the use case owing it a §7.6 error did not produce one."""

    def test_an_invariant_violation_maps_to_500_without_leaking(self) -> None:
        response = _client().get("/domain-invariant")

        assert response.status_code == 500
        assert response.json()["error"]["details"] == {}
        assert "norm=" not in response.text

    def test_the_reason_reaches_the_log(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The body carries nothing, so this line is the only place the cause survives.
        configure_logging()

        _client().get("/domain-invariant")

        assert _INTERNAL_INVARIANT_MESSAGE in capsys.readouterr().out

    def test_an_untranslated_field_error_is_also_500_not_a_guessed_4xx(self) -> None:
        response = _client().get("/untranslated-field-error")

        assert response.status_code == 500
        assert response.json()["error"]["details"] == {}
        assert "name" not in response.json()["error"]["message"]

    def test_an_untranslated_subclass_is_covered_by_the_same_registration(self) -> None:
        # `ChunkCountExceededError` is a `DomainValidationError`; handler lookup walks the
        # MRO, so registering the base covers it — which is what makes "the use case that
        # forgot to translate it" a 500 rather than an unhandled crash.
        response = _client().get("/untranslated-chunk-count")

        assert response.status_code == 500
        assert response.json()["error"]["code"] == "InternalError"
