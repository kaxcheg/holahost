"""This service's half of the exception -> envelope mapping.

The machinery is `holahost_http.register_error_handlers`' and is tested there: the MRO walk,
the closed vocabulary, the bare-`Exception` path and its header echo, the log level following
the status. What is left here is what this service decides — which errors it publishes and
with what status, and that its own untranslated domain-invariant violation, and the storage
failures it passes through on purpose, are answered `500` rather than reaching Starlette's
re-raising handler.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from holahost_http import InvalidPayloadError, NotFoundError, RequestIdMiddleware
from tests._support.http import register_test_handlers

from application.ports.exceptions import (
    ConcurrentUpdateError,
    IntegrityError,
    ProviderRejectedRequestError,
    StorageUnavailableError,
)
from config.logging import configure_logging
from domain.exceptions import DomainValidationError
from interface.http.errors import ERROR_CONTRACT

_INTERNAL_INVARIANT_MESSAGE = "Total must not be negative (got total=-3)"


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_test_handlers(app)

    @app.get("/invalid-payload")
    def invalid_payload() -> None:
        raise InvalidPayloadError(field="name")

    @app.get("/not-found")
    def not_found() -> None:
        raise NotFoundError

    @app.get("/domain-invariant")
    def domain_invariant() -> None:
        # What a value object or entity raises when an invariant no caller could have
        # violated is broken — `field` unset, so nothing upstream translated it.
        raise DomainValidationError(_INTERNAL_INVARIANT_MESSAGE)

    @app.get("/untranslated-field-error")
    def untranslated_field_error() -> None:
        # The other half: the caller's to fix, but the use case did not translate it.
        raise DomainValidationError("Name must not be empty", field="name")

    @app.get("/storage-unavailable")
    def storage_unavailable() -> None:
        raise StorageUnavailableError("connection to server at 10.0.0.5 failed")

    @app.get("/concurrent-update")
    def concurrent_update() -> None:
        raise ConcurrentUpdateError("canceling statement due to statement timeout")

    @app.get("/missing-grant")
    def missing_grant() -> None:
        raise IntegrityError("permission denied for table usage_records")

    @app.get("/vendor-rejection")
    def vendor_rejection() -> None:
        raise ProviderRejectedRequestError("invalid x-api-key sk-ant-1234", status=401)

    return app


def _client() -> TestClient:
    # `raise_server_exceptions` stays on, and that is what pins the registration: a type
    # missing from `SILENT_500_TYPES` still gets the same `500` envelope and log line from the
    # bare-`Exception` handler, which then re-raises — the traceback outside the JSON log. With
    # the flag off the re-raise is swallowed and a missing registration passes every check.
    return TestClient(_build_app())


class TestTheContract:
    def test_every_published_error_answers_its_declared_status(self) -> None:
        """The table decides, so a changed number shows up as a changed test rather than a
        changed handler."""
        client = _client()

        for path, error in [
            ("/invalid-payload", InvalidPayloadError),
            ("/not-found", NotFoundError),
        ]:
            response = client.get(path)
            assert response.status_code == ERROR_CONTRACT[error], path
            assert response.json()["error"]["code"] == error.__name__, path


class TestDomainValidationErrorIsInternal:
    """The `SILENT_500_TYPES` wiring. Both halves are a defect: an unset `field` is internal by
    definition, and a `field`-carrying one that got this far means the use case owing it a
    published error did not produce one."""

    def test_an_invariant_violation_is_500_without_leaking(self) -> None:
        response = _client().get("/domain-invariant")

        assert response.status_code == 500
        assert response.json()["error"] == {
            "code": "InternalError",
            "message": "internal error",
            "details": {},
        }
        assert "total=" not in response.text

    def test_the_reason_reaches_the_log(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The body carries nothing, so this line is the only place the cause survives.
        configure_logging()

        _client().get("/domain-invariant")

        assert _INTERNAL_INVARIANT_MESSAGE in capsys.readouterr().out

    def test_an_untranslated_field_error_is_also_500_not_a_guessed_4xx(self) -> None:
        response = _client().get("/untranslated-field-error")

        assert response.status_code == 500
        assert response.json()["error"]["details"] == {}


class TestPassedThroughFailuresAreInternal:
    """What the use case lets through on purpose, to be answered `500`: a budget read's storage
    failure — retrying within the request is pointless, and generating without the check would
    be unaccounted spend — and every candidate's vendor rejecting the request, which is this
    service's own defect."""

    @pytest.mark.parametrize(
        "path",
        ["/storage-unavailable", "/concurrent-update", "/missing-grant", "/vendor-rejection"],
    )
    def test_is_500_without_leaking(self, path: str) -> None:
        response = _client().get(path)

        assert response.status_code == 500
        assert response.json()["error"]["code"] == "InternalError"
        for fragment in ("10.0.0.5", "statement", "usage_records", "sk-ant"):
            assert fragment not in response.text
