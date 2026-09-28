"""This service's half of the exception -> envelope mapping.

The machinery is `holahost_http.register_error_handlers`' and is tested there: the MRO walk,
the closed vocabulary, the bare-`Exception` path and its header echo, the log level following
the status. What is left here is what this service decides — which errors it publishes and
with what status, and that its own untranslated domain-invariant violation, and the storage
failures it passes through on purpose, are answered `500` rather than reaching Starlette's
re-raising handler.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from holahost_http import InvalidPayloadError, NotFoundError, PlatformError, RequestIdMiddleware
from tests._support.http import register_test_handlers

from application.exceptions import (
    BudgetExhaustedError,
    ContentRefusedError,
    ContextOverflowError,
    DuplicateRequestError,
    RequestTooSlowForSyncError,
    UnknownModelError,
    UpstreamLlmError,
    UsageNotRecordedError,
)
from application.ports.exceptions import (
    ConcurrentUpdateError,
    IntegrityError,
    ProviderRejectedRequestError,
    StorageUnavailableError,
)
from config.logging import SERVICE_LOG_FIELDS, configure_logging
from domain.exceptions import DomainValidationError
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.idempotency_state import IdempotencyState
from interface.http.errors import ERROR_CONTRACT

_INTERNAL_INVARIANT_MESSAGE = "Total must not be negative (got total=-3)"

_PUBLISHED: dict[str, PlatformError] = {
    "/invalid-payload": InvalidPayloadError(field="messages"),
    "/unknown-model": UnknownModelError(requested="huge", available_aliases=["fast"]),
    "/context-overflow": ContextOverflowError(max_context=10, estimated=20),
    "/too-slow": RequestTooSlowForSyncError(max_tokens_allowed=100, budget_seconds=20.0),
    "/duplicate": DuplicateRequestError(state=IdempotencyState.IN_FLIGHT),
    "/budget-exhausted": BudgetExhaustedError(
        scope=BudgetScope.CLIENT, resets_at=datetime.now(tz=UTC) + timedelta(hours=2)
    ),
    "/content-refused": ContentRefusedError(
        provider="anthropic", model="m", input_tokens=40, output_tokens=0
    ),
    "/upstream": UpstreamLlmError(attempts=2, upstream_status=None, provider_timeouts=2),
}


def _raising(error: PlatformError) -> Callable[[], None]:
    def route() -> None:
        raise error

    return route


def _last_event(captured: str) -> dict[str, Any]:
    event: dict[str, Any] = json.loads(captured.strip().splitlines()[-1])
    return event


def _build_app() -> FastAPI:
    # The service's fields declared, as `bootstrap` does: an error reporting a field outside the
    # allowlist fails in its own handler.
    configure_logging()
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_test_handlers(app)

    for path, error in _PUBLISHED.items():
        app.add_api_route(path, _raising(error))

    @app.get("/not-found")
    def not_found() -> None:
        raise NotFoundError

    @app.get("/usage-not-recorded")
    def usage_not_recorded() -> None:
        raise UsageNotRecordedError(
            input_tokens=120,
            output_tokens=30,
            provider="anthropic",
            model="claude-haiku-4-5",
            cause=StorageUnavailableError(),
        )

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
    @pytest.mark.parametrize(
        ("path", "status"),
        [
            ("/invalid-payload", 422),
            ("/unknown-model", 400),
            ("/context-overflow", 422),
            ("/too-slow", 422),
            ("/duplicate", 409),
            ("/budget-exhausted", 429),
            ("/content-refused", 422),
            ("/upstream", 502),
        ],
    )
    def test_every_published_error_answers_its_declared_status(
        self, path: str, status: int
    ) -> None:
        """Spelled out rather than read back from the table, so a changed number shows up as a
        changed test rather than a changed handler."""
        error = _PUBLISHED[path]

        response = _client().get(path)

        assert ERROR_CONTRACT[type(error)] == status
        assert response.status_code == status
        assert response.json()["error"]["code"] == error.code

    def test_the_platform_s_not_found_is_not_this_service_s_to_publish(self) -> None:
        # llm-client addresses no resource by id; a stray `NotFoundError` is a defect.
        assert _client().get("/not-found").status_code == 500

    def test_a_budget_refusal_says_when_to_come_back(self) -> None:
        response = _client().get("/budget-exhausted")

        # Two hours ahead when the module was imported; the suite's own run time comes off it.
        assert 6000 < int(response.headers["Retry-After"]) <= 7200

    def test_the_rate_limit_style_header_is_on_no_other_refusal(self) -> None:
        assert "Retry-After" not in _client().get("/upstream").headers


class TestTheCompletionEventOfARefusal:
    @pytest.mark.parametrize("error", list(_PUBLISHED.values()), ids=lambda e: type(e).__name__)
    def test_every_field_an_error_reports_is_declared(self, error: PlatformError) -> None:
        # Outside the allowlist, `log_event` raises inside the exception handler, and the
        # refusal the error stands for turns into a traceback.
        assert set(error.log_fields()) <= SERVICE_LOG_FIELDS

    def test_the_unpublished_error_s_fields_are_declared_too(self) -> None:
        error = UsageNotRecordedError(
            input_tokens=1, output_tokens=1, provider="p", model="m", cause=IntegrityError()
        )
        assert set(error.log_fields()) <= SERVICE_LOG_FIELDS

    def test_an_upstream_failure_reports_its_attempts_and_timeouts(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging()

        _client().get("/upstream")

        event = _last_event(capsys.readouterr().out)
        assert (event["outcome"], event["attempts"], event["provider_timeouts"]) == (
            "UpstreamLlmError",
            2,
            2,
        )

    def test_an_unrecorded_spend_still_reaches_the_event(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging()

        response = _client().get("/usage-not-recorded")

        event = _last_event(capsys.readouterr().out)
        assert response.status_code == 500
        assert event["outcome"] == "InternalError"
        assert (event["input_tokens"], event["output_tokens"]) == (120, 30)
        assert (event["provider"], event["model"]) == ("anthropic", "claude-haiku-4-5")


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
