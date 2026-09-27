"""GenerateUseCase: what happens to an idempotency key, by how the request ended."""

from __future__ import annotations

import pytest
from tests._support.builders import (
    CLIENT,
    HAIKU,
    exhausted_budget,
    make_cmd,
    make_generation,
    make_usage,
)
from tests._support.generate import build_use_case, fails, ok

from application.exceptions import (
    BudgetExhaustedError,
    ContentRefusedError,
    DuplicateRequestError,
    UpstreamLlmError,
    UsageNotRecordedError,
)
from application.ports.exceptions import (
    ProviderRefusedContentError,
    ProviderRejectedRequestError,
    StorageUnavailableError,
    TransientProviderError,
)
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from domain.value_objects.idempotency_state import IdempotencyState


def _overloaded() -> TransientProviderError:
    return TransientProviderError("overloaded", status=529, retry_after=None)


class TestDuplicates:
    def test_a_duplicate_is_refused_before_anything_else(self) -> None:
        h = build_use_case(duplicate=IdempotencyState.IN_FLIGHT)

        with pytest.raises(DuplicateRequestError) as exc:
            h.use_case.execute(make_cmd(idempotency_key="k-1"))

        assert exc.value.details_dict() == {"state": "in_flight"}
        assert h.budgets.reads == []
        assert h.generation.calls == []
        # The key belongs to the request already holding it: releasing it here would unblock the
        # very repeat it exists to stop.
        assert h.idempotency.released == []


class TestAnsweredRequests:
    def test_success_completes_the_key_with_the_usage(self) -> None:
        answer = make_generation(usage=make_usage(50, 7))
        h = build_use_case(script={HAIKU.id.value: [ok(generation=answer)]})

        h.use_case.execute(make_cmd(idempotency_key="k-1"))

        assert h.idempotency.begun == [(CLIENT, "k-1")]
        assert h.idempotency.completed == [(CLIENT, "k-1", make_usage(50, 7))]
        assert h.idempotency.released == []

    def test_a_refusal_completes_the_key(self) -> None:
        # The refused call was paid for; a repeat with the same key would pay for the same
        # refusal again.
        h = build_use_case(
            script={HAIKU.id.value: [fails(ProviderRefusedContentError(usage=make_usage(40, 0)))]}
        )

        with pytest.raises(ContentRefusedError):
            h.use_case.execute(make_cmd(idempotency_key="k-1"))

        assert h.idempotency.completed == [(CLIENT, "k-1", make_usage(40, 0))]
        assert h.idempotency.released == []

    def test_a_failed_record_completes_the_key_too(self) -> None:
        # The provider answered and charged; only the write failed. Releasing the key would let the
        # repeat buy the same answer a second time, for as long as the database is down.
        h = build_use_case(usage_errors=[StorageUnavailableError()])

        with pytest.raises(UsageNotRecordedError):
            h.use_case.execute(make_cmd(idempotency_key="k-1"))

        assert h.idempotency.completed == [(CLIENT, "k-1", make_usage())]
        assert h.idempotency.released == []


class TestFailedRequests:
    def test_a_budget_refusal_releases_the_key(self) -> None:
        h = build_use_case(budgets=[exhausted_budget(BudgetScope.CLIENT, ClientId(CLIENT))])

        with pytest.raises(BudgetExhaustedError):
            h.use_case.execute(make_cmd(idempotency_key="k-1"))

        assert h.idempotency.released == [(CLIENT, "k-1")]
        assert h.idempotency.completed == []

    def test_an_upstream_failure_releases_the_key(self) -> None:
        h = build_use_case(script={HAIKU.id.value: [fails(_overloaded()), fails(_overloaded())]})

        with pytest.raises(UpstreamLlmError):
            h.use_case.execute(make_cmd(idempotency_key="k-1"))

        assert h.idempotency.released == [(CLIENT, "k-1")]

    def test_a_rejection_releases_the_key(self) -> None:
        h = build_use_case(
            script={HAIKU.id.value: [fails(ProviderRejectedRequestError("revoked", status=401))]}
        )

        with pytest.raises(ProviderRejectedRequestError):
            h.use_case.execute(make_cmd(idempotency_key="k-1"))

        assert h.idempotency.released == [(CLIENT, "k-1")]


class TestWithoutAKey:
    def test_the_store_is_not_touched(self) -> None:
        h = build_use_case()

        h.use_case.execute(make_cmd(idempotency_key=None))

        assert (h.idempotency.begun, h.idempotency.completed, h.idempotency.released) == (
            [],
            [],
            [],
        )
