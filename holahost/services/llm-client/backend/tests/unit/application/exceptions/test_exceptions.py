"""Tests for the application-layer, HTTP-facing exception hierarchy.

Every `code` asserted below is the class's own name, and that is the point: renaming a class is a
change to the wire contract and must fail loudly here. `details` is compared whole — a key added,
dropped or renamed is a schema change too.

`InvalidPayloadError`, `MalformedRequestError` and `NotFoundError` are absent: they are the
platform's, defined and tested in `holahost-http`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from application.exceptions import (
    ApplicationError,
    BudgetExhaustedError,
    ContentRefusedError,
    ContextOverflowError,
    DuplicateRequestError,
    RequestTooSlowForSyncError,
    UnknownModelError,
    UpstreamLlmError,
    UsageNotRecordedError,
)
from application.ports.exceptions import IntegrityError
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.idempotency_state import IdempotencyState


class TestApplicationError:
    def test_the_base_is_not_a_published_error(self) -> None:
        error = ApplicationError("boom")
        assert error.code == "ApplicationError"
        assert error.details_dict() == {}


class TestUnknownModelError:
    def test_wire_shape(self) -> None:
        error = UnknownModelError(requested="huge", available_aliases=["default", "fast"])
        assert error.code == "UnknownModelError"
        assert error.details_dict() == {
            "requested": "huge",
            "available_aliases": ["default", "fast"],
        }


class TestContextOverflowError:
    def test_wire_shape(self) -> None:
        error = ContextOverflowError(max_context=200_000, estimated=210_016)
        assert error.code == "ContextOverflowError"
        assert error.details_dict() == {"max_context": 200_000, "estimated": 210_016}


class TestRequestTooSlowForSyncError:
    def test_wire_shape(self) -> None:
        error = RequestTooSlowForSyncError(max_tokens_allowed=500, budget_seconds=5.0)
        assert error.code == "RequestTooSlowForSyncError"
        assert error.details_dict() == {"max_tokens_allowed": 500, "budget_seconds": 5.0}


class TestDuplicateRequestError:
    def test_wire_shape(self) -> None:
        error = DuplicateRequestError(state=IdempotencyState.IN_FLIGHT)
        assert error.code == "DuplicateRequestError"
        assert error.details_dict() == {"state": "in_flight"}

    def test_keeps_the_state(self) -> None:
        error = DuplicateRequestError(state=IdempotencyState.COMPLETED)
        assert error.state is IdempotencyState.COMPLETED


class TestBudgetExhaustedError:
    def test_wire_shape(self) -> None:
        resets_at = datetime(2026, 9, 15, tzinfo=UTC)
        error = BudgetExhaustedError(scope=BudgetScope.CLIENT_DOWNGRADE, resets_at=resets_at)
        assert error.code == "BudgetExhaustedError"
        assert error.details_dict() == {
            "scope": "client_downgrade",
            "resets_at": "2026-09-15T00:00:00+00:00",
        }

    def test_keeps_the_reset_time_for_retry_after(self) -> None:
        resets_at = datetime(2026, 9, 15, tzinfo=UTC)
        error = BudgetExhaustedError(scope=BudgetScope.PROVIDER, resets_at=resets_at)
        assert error.resets_at == resets_at


class TestUpstreamLlmError:
    def test_wire_shape(self) -> None:
        error = UpstreamLlmError(attempts=2, upstream_status=529, provider_timeouts=0)
        assert error.code == "UpstreamLlmError"
        assert error.details_dict() == {"attempts": 2, "upstream_status": 529}

    def test_a_timeout_has_no_upstream_status(self) -> None:
        error = UpstreamLlmError(attempts=1, upstream_status=None, provider_timeouts=0)
        assert error.details_dict() == {"attempts": 1, "upstream_status": None}

    def test_timeouts_stay_out_of_the_wire_shape(self) -> None:
        error = UpstreamLlmError(attempts=2, upstream_status=None, provider_timeouts=2)
        assert error.details_dict() == {"attempts": 2, "upstream_status": None}
        assert error.provider_timeouts == 2


class TestContentRefusedError:
    def test_wire_shape(self) -> None:
        error = ContentRefusedError(provider="anthropic", model="claude-haiku-4-5")
        assert error.code == "ContentRefusedError"
        assert error.details_dict() == {"provider": "anthropic", "model": "claude-haiku-4-5"}


class TestUsageNotRecordedError:
    def _error(self) -> UsageNotRecordedError:
        return UsageNotRecordedError(
            input_tokens=120,
            output_tokens=30,
            provider="anthropic",
            model="claude-haiku-4-5",
            cause=IntegrityError(),
        )

    def test_is_published_by_no_contract(self) -> None:
        error = self._error()
        assert error.code == "UsageNotRecordedError"
        assert error.details_dict() == {}

    def test_keeps_the_confirmed_spend(self) -> None:
        error = self._error()
        assert (error.input_tokens, error.output_tokens) == (120, 30)
        assert (error.provider, error.model) == ("anthropic", "claude-haiku-4-5")

    def test_names_the_storage_failure_for_the_log(self) -> None:
        # The storage failures carry no message of their own: without the name, a defect would
        # read the same as an outage.
        assert str(self._error()) == "usage not recorded: IntegrityError"


class TestEveryErrorIsTheServices:
    def test_each_subclasses_application_error(self) -> None:
        errors: list[ApplicationError] = [
            UnknownModelError(requested="x", available_aliases=[]),
            ContextOverflowError(max_context=1, estimated=2),
            RequestTooSlowForSyncError(max_tokens_allowed=0, budget_seconds=0.0),
            DuplicateRequestError(state=IdempotencyState.IN_FLIGHT),
            BudgetExhaustedError(
                scope=BudgetScope.CLIENT, resets_at=datetime(2026, 9, 15, tzinfo=UTC)
            ),
            UpstreamLlmError(attempts=1, upstream_status=None, provider_timeouts=0),
            ContentRefusedError(provider="p", model="m"),
            UsageNotRecordedError(
                input_tokens=1, output_tokens=1, provider="p", model="m", cause=IntegrityError()
            ),
        ]
        assert len({error.code for error in errors}) == len(errors)
