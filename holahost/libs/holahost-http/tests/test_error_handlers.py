"""The exception -> envelope mapping, tested through a service-shaped app.

What belongs to a service (which errors exist, which status each answers with) arrives
as `contract`; everything asserted here is the machinery around it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from holahost_observability import configure_logging
from pydantic import BaseModel

from holahost_http import (
    ErrorContract,
    InvalidPayloadError,
    NotFoundError,
    PlatformError,
    RequestIdMiddleware,
    add_log_fields,
    log_completion,
    register_error_handlers,
)

_INTERNAL_DETAIL = "Embedding must be L2-normalized (got norm=0.9993)"


class _ServiceError(PlatformError):
    """A service's own base — never published, so an instance of it is out of contract."""


class _TooLargeError(_ServiceError):
    def __init__(self, limit: int, actual: int) -> None:
        super().__init__("too large")
        self.limit = limit
        self.actual = actual

    def details_dict(self) -> dict[str, object]:
        return {"limit": self.limit, "actual": self.actual}


class _RetryLaterError(_ServiceError):
    """Owes a header, the way a refusal with a known end owes `Retry-After`."""

    def headers(self) -> Mapping[str, str]:
        return {"Retry-After": "42"}


class _UnpublishedRetryError(_ServiceError):
    """Owes a header, but nobody published it — answered as out of contract."""

    def headers(self) -> Mapping[str, str]:
        return {"Retry-After": "42"}


class _CountedError(_ServiceError):
    """Carries completion-event fields the response must not show."""

    def log_fields(self) -> Mapping[str, object]:
        return {"attempts": 3}


class _UnpublishedCountedError(_ServiceError):
    def log_fields(self) -> Mapping[str, object]:
        return {"attempts": 3}


class _CoreNamedError(_ServiceError):
    """Reports a field named like a core one — which only the platform writes."""

    def log_fields(self) -> Mapping[str, object]:
        return {"error_reason": "from the service", "attempts": 1}


class _DerivedNotFoundError(NotFoundError):
    """A subclass nobody put in the table — it must still map to its base's status."""


class _DomainInvariantError(ValueError):
    """Stands in for a service's domain-invariant violation: answered 500, but through
    an ordinary handler rather than Starlette's re-raising bare-`Exception` path."""


class _Body(BaseModel):
    x: int


_CONTRACT: ErrorContract = {
    _TooLargeError: 413,
    _RetryLaterError: 429,
    _CountedError: 502,
    _CoreNamedError: 409,
    InvalidPayloadError: 422,
    NotFoundError: 404,
}


def _build_app(*, contract: ErrorContract = _CONTRACT) -> FastAPI:
    configure_logging(extra_fields={"attempts", "requested"})
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(
        app,
        contract=contract,
        silent_500_types=(_DomainInvariantError,),
    )

    @app.get("/too-large")
    def too_large() -> None:
        raise _TooLargeError(limit=100, actual=200)

    @app.get("/retry-later")
    def retry_later() -> None:
        raise _RetryLaterError("later")

    @app.get("/unpublished-retry")
    def unpublished_retry() -> None:
        raise _UnpublishedRetryError("later")

    @app.get("/counted")
    def counted(request: Request) -> None:
        add_log_fields(request, requested="fast")
        raise _CountedError("gave up")

    @app.get("/counted-unpublished")
    def counted_unpublished() -> None:
        raise _UnpublishedCountedError("gave up")

    @app.get("/core-named")
    def core_named() -> None:
        raise _CoreNamedError("conflict")

    @app.get("/success")
    def success(request: Request) -> None:
        add_log_fields(request, requested="fast")
        log_completion(request, outcome="success", fields={"attempts": 1})

    @app.get("/annotated-invariant")
    def annotated_invariant(request: Request) -> None:
        add_log_fields(request, requested="fast")
        raise _DomainInvariantError(_INTERNAL_DETAIL)

    @app.get("/not-found")
    def not_found() -> None:
        raise NotFoundError

    @app.get("/derived-not-found")
    def derived_not_found() -> None:
        raise _DerivedNotFoundError

    @app.get("/unpublished")
    def unpublished() -> None:
        raise _ServiceError(_INTERNAL_DETAIL)

    @app.get("/domain-invariant")
    def domain_invariant() -> None:
        raise _DomainInvariantError(_INTERNAL_DETAIL)

    @app.post("/validated")
    def validated(body: _Body) -> None:
        return None

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("unexpected")

    return app


def _client() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


class TestTheContractDecidesTheAnswer:
    def test_a_published_error_answers_with_its_status_identity_and_details(self) -> None:
        response = _client().get("/too-large")

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "_TooLargeError"
        assert response.json()["error"]["details"] == {"limit": 100, "actual": 200}

    def test_an_unpublished_subclass_is_answered_as_its_published_ancestor(self) -> None:
        # The lookup walks the MRO and takes the *identity* from the matched ancestor: a
        # subclass has no entry in the service's published schema, so answering with its
        # own name would put an identity on the wire the schema does not describe.
        response = _client().get("/derived-not-found")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NotFoundError"

    def test_an_error_outside_the_contract_is_internal_and_says_nothing(self) -> None:
        response = _client().get("/unpublished")

        assert response.status_code == 500
        assert response.json()["error"] == {
            "code": "InternalError",
            "message": "internal error",
            "details": {},
        }
        assert "norm=" not in response.text


class TestSilent500Types:
    """Registered as ordinary handlers rather than left to the bare-`Exception` one:
    that one is bound to `ServerErrorMiddleware`, which re-raises after writing the
    response, so uvicorn prints an unstructured traceback outside the JSON log."""

    def test_the_body_leaks_nothing(self) -> None:
        response = _client().get("/domain-invariant")

        assert response.status_code == 500
        assert response.json()["error"]["details"] == {}
        assert "norm=" not in response.text

    def test_the_cause_reaches_the_log(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The body carries nothing, so this line is the only place the cause survives.
        _client().get("/domain-invariant")

        assert _INTERNAL_DETAIL in capsys.readouterr().out


class TestFrameworkValidation:
    def test_a_rejected_body_answers_the_platform_error(self) -> None:
        response = _client().post("/validated", json={})

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "InvalidPayloadError"
        # One identity, one set of `details` keys: `limit` is present (null) rather than
        # absent, so a consumer never has to know which raise site answered.
        assert response.json()["error"]["details"] == {"field": "x", "limit": None}

    def test_a_contract_without_invalid_payload_is_refused_at_registration(self) -> None:
        # A wiring defect found when the app is built, not on the first malformed
        # request — which on a service with no request bodies could be much later, since
        # a path or query parameter reaches the same handler.
        with pytest.raises(RuntimeError, match="InvalidPayloadError"):
            _build_app(contract={NotFoundError: 404})


class TestUnexpectedExceptions:
    def test_a_bare_exception_leaks_nothing(self) -> None:
        response = _client().get("/boom")

        assert response.status_code == 500
        assert response.json()["error"]["code"] == "InternalError"
        assert "RuntimeError" not in str(response.json())
        assert "unexpected" not in str(response.json())

    def test_a_bare_exception_still_echoes_the_request_id(self) -> None:
        # Starlette binds the bare-`Exception` handler to the outermost
        # ServerErrorMiddleware, outside the user middleware — RequestIdMiddleware's own
        # header echo never runs for this one path, so the handler does it itself.
        response = _client().get("/boom", headers={"X-Request-ID": "req-500"})

        assert response.headers["X-Request-ID"] == "req-500"

    def test_a_routing_404_is_answered_as_starlette_shapes_it(self) -> None:
        # A different fact from an application-level NotFoundError, and it keeps
        # Starlette's `{"detail": ...}` rather than being dressed as a service error.
        response = _client().get("/no-such-route")

        assert response.status_code == 404
        assert "error" not in response.json()


def _last_event(captured: str) -> dict[str, Any]:
    event: dict[str, Any] = json.loads(captured.strip().splitlines()[-1])
    return event


class TestErrorHeaders:
    def test_a_published_error_carries_the_headers_it_owes(self) -> None:
        response = _client().get("/retry-later")

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "42"

    def test_an_error_that_owes_none_adds_none(self) -> None:
        assert "Retry-After" not in _client().get("/too-large").headers

    def test_an_out_of_contract_error_answers_without_them(self) -> None:
        # The 500 is not the error that owed the header: telling a caller when to come back
        # for an answer the service never published would be advice about the wrong fact.
        response = _client().get("/unpublished-retry")

        assert response.status_code == 500
        assert "Retry-After" not in response.headers


class TestCompletionEventFields:
    def test_a_published_error_reports_its_fields_and_the_request_s(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        response = _client().get("/counted")

        event = _last_event(capsys.readouterr().out)
        assert event["outcome"] == "_CountedError"
        assert event["attempts"] == 3
        assert event["requested"] == "fast"
        assert "attempts" not in response.json()["error"]["details"]

    def test_an_out_of_contract_error_still_reports_its_fields(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Answered 500 with nothing in the body, so the event is the only place the figures
        # it carries survive.
        _client().get("/counted-unpublished")

        event = _last_event(capsys.readouterr().out)
        assert event["outcome"] == "InternalError"
        assert event["attempts"] == 3

    def test_a_silent_500_reports_the_request_s_fields(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _client().get("/annotated-invariant")

        event = _last_event(capsys.readouterr().out)
        assert event["outcome"] == "InternalError"
        assert event["requested"] == "fast"

    def test_a_field_named_like_a_core_one_is_dropped_not_fatal(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Failing inside the handler would turn a published 409 into a traceback 500.
        response = _client().get("/core-named")

        event = _last_event(capsys.readouterr().out)
        assert response.status_code == 409
        assert event["error_reason"] is None
        assert event["attempts"] == 1

    def test_a_route_may_not_attach_a_core_field(self) -> None:
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
        with pytest.raises(ValueError, match="outcome"):
            add_log_fields(request, outcome="success")


class TestTheSuccessLine:
    def test_is_assembled_like_a_refusal_s_with_the_route_s_fields(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # One core for both lines, so a filter on `route` counts every outcome of the route.
        _client().get("/success", headers={"X-Request-ID": "req-ok"})

        event = _last_event(capsys.readouterr().out)
        assert (event["route"], event["outcome"]) == ("GET /success", "success")
        assert event["request_id"] == "req-ok"
        assert event["level"] == logging.getLevelName(logging.INFO)
        assert (event["requested"], event["attempts"]) == ("fast", 1)


class TestTheLogLevelFollowsTheStatus:
    """The formatter writes a `level` on every line, so it has to mean something.
    Filters match `$.outcome` and never read it — it is for a person."""

    @staticmethod
    def _last_level(captured: str) -> str:
        return str(json.loads(captured.strip().splitlines()[-1])["level"])

    def test_a_5xx_is_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        _client().get("/boom")

        assert self._last_level(capsys.readouterr().out) == logging.getLevelName(logging.ERROR)

    def test_a_4xx_is_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        _client().get("/not-found")

        assert self._last_level(capsys.readouterr().out) == logging.getLevelName(logging.WARNING)

    def test_the_status_drives_it_not_the_outcome_string(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # `handle_http_exception` logs a bare numeric outcome ("404"), so the level has
        # to come from the status being answered with, not from parsing that string.
        _client().get("/no-such-route")

        assert self._last_level(capsys.readouterr().out) == logging.getLevelName(logging.WARNING)
