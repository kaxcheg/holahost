"""GenerateUseCase: the provider's and the client's budgets, and the client's exhaustion policy."""

from __future__ import annotations

from datetime import timedelta

import pytest
from tests._support.builders import (
    ANTHROPIC,
    CLIENT,
    FALLBACK,
    HAIKU,
    OTHER_VENDOR,
    SONNET,
    WINDOW_START,
    exhausted_budget,
    make_cmd,
    make_model,
)
from tests._support.generate import build_use_case, ok

from application.exceptions import BudgetExhaustedError, RequestTooSlowForSyncError
from application.ports.exceptions import (
    ConcurrentUpdateError,
    IntegrityError,
    StorageUnavailableError,
)
from domain.value_objects.budget_policy import BudgetPolicy
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId

_CLIENT_ID = ClientId(CLIENT)


class TestProviderBudget:
    def test_an_exhausted_provider_is_refused_whatever_the_policy(self) -> None:
        h = build_use_case(
            budgets=[exhausted_budget(BudgetScope.PROVIDER, ANTHROPIC.name)],
            default_policy=BudgetPolicy.DOWNGRADE,
            downgrade=[FALLBACK],
        )

        with pytest.raises(BudgetExhaustedError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.scope is BudgetScope.PROVIDER
        assert exc.value.resets_at == WINDOW_START + timedelta(days=1)
        assert h.budgets.reads == [(BudgetScope.PROVIDER, "anthropic")]
        assert h.generation.calls == []

    def test_an_exhausted_first_provider_is_passed_over(self) -> None:
        h = build_use_case(
            routes={"fast": [HAIKU, FALLBACK]},
            budgets=[exhausted_budget(BudgetScope.PROVIDER, ANTHROPIC.name)],
            script={FALLBACK.id.value: [ok()]},
        )

        result = h.use_case.execute(make_cmd())

        assert (result.model, result.failed_over) == ("other-vendor-mini", True)
        assert h.generation.called_models() == ["other-vendor-mini"]
        assert h.budgets.reads == [
            (BudgetScope.PROVIDER, "anthropic"),
            (BudgetScope.PROVIDER, "other-vendor"),
            (BudgetScope.CLIENT, CLIENT),
        ]

    def test_every_candidates_provider_exhausted_is_refused(self) -> None:
        h = build_use_case(
            routes={"fast": [HAIKU, FALLBACK]},
            budgets=[
                exhausted_budget(BudgetScope.PROVIDER, ANTHROPIC.name),
                exhausted_budget(BudgetScope.PROVIDER, OTHER_VENDOR.name),
            ],
        )

        with pytest.raises(BudgetExhaustedError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.scope is BudgetScope.PROVIDER
        assert h.generation.calls == []

    def test_a_candidate_that_cannot_serve_does_not_rescue_an_exhausted_first(self) -> None:
        small = make_model(
            "other-vendor-mini", provider=OTHER_VENDOR, max_context=1050, max_output=1000
        )
        h = build_use_case(
            routes={"fast": [HAIKU, small]},
            budgets=[exhausted_budget(BudgetScope.PROVIDER, ANTHROPIC.name)],
        )

        with pytest.raises(BudgetExhaustedError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.scope is BudgetScope.PROVIDER


class TestClientBudget:
    def test_within_budget_reads_only_the_provider_and_the_client(self) -> None:
        h = build_use_case()
        h.use_case.execute(make_cmd())
        assert h.budgets.reads == [
            (BudgetScope.PROVIDER, "anthropic"),
            (BudgetScope.CLIENT, CLIENT),
        ]

    def test_exhausted_under_reject_is_refused(self) -> None:
        h = build_use_case(budgets=[exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID)])

        with pytest.raises(BudgetExhaustedError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.scope is BudgetScope.CLIENT
        assert h.generation.calls == []

    def test_a_downgrade_override_beats_a_reject_default(self) -> None:
        h = build_use_case(
            budgets=[exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID)],
            default_policy=BudgetPolicy.REJECT,
            overrides={_CLIENT_ID: BudgetPolicy.DOWNGRADE},
            downgrade=[SONNET],
            script={SONNET.id.value: [ok()]},
        )

        result = h.use_case.execute(make_cmd())

        assert (result.model, result.downgraded) == ("claude-sonnet-4-6", True)

    def test_a_reject_override_beats_a_downgrade_default(self) -> None:
        h = build_use_case(
            budgets=[exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID)],
            default_policy=BudgetPolicy.DOWNGRADE,
            overrides={_CLIENT_ID: BudgetPolicy.REJECT},
            downgrade=[SONNET],
        )

        with pytest.raises(BudgetExhaustedError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.scope is BudgetScope.CLIENT


class TestDowngrade:
    def test_no_target_is_refused_on_the_client_budget(self) -> None:
        h = build_use_case(
            budgets=[exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID)],
            default_policy=BudgetPolicy.DOWNGRADE,
            downgrade=[],
        )

        with pytest.raises(BudgetExhaustedError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.scope is BudgetScope.CLIENT

    def test_an_exhausted_downgrade_pool_is_refused(self) -> None:
        h = build_use_case(
            budgets=[
                exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID),
                exhausted_budget(BudgetScope.CLIENT_DOWNGRADE, _CLIENT_ID),
            ],
            default_policy=BudgetPolicy.DOWNGRADE,
            downgrade=[SONNET],
        )

        with pytest.raises(BudgetExhaustedError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.scope is BudgetScope.CLIENT_DOWNGRADE
        assert h.generation.calls == []

    def test_a_target_whose_provider_is_exhausted_is_passed_over(self) -> None:
        h = build_use_case(
            budgets=[
                exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID),
                exhausted_budget(BudgetScope.PROVIDER, OTHER_VENDOR.name),
            ],
            default_policy=BudgetPolicy.DOWNGRADE,
            downgrade=[FALLBACK, SONNET],
            script={SONNET.id.value: [ok()]},
        )

        result = h.use_case.execute(make_cmd())

        assert result.model == "claude-sonnet-4-6"
        assert FALLBACK.id.value not in h.generation.called_models()

    def test_a_target_too_small_for_the_request_is_passed_over(self) -> None:
        small = make_model("small", max_context=1050, max_output=1000)
        h = build_use_case(
            budgets=[exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID)],
            default_policy=BudgetPolicy.DOWNGRADE,
            downgrade=[small, SONNET],
            script={SONNET.id.value: [ok()]},
        )

        result = h.use_case.execute(make_cmd())

        assert (result.model, result.downgraded) == ("claude-sonnet-4-6", True)

    def test_when_no_target_can_serve_the_clients_own_budget_is_the_answer(self) -> None:
        # The caller never asked for the cheaper model, so its context and speed are not what the
        # caller is told about: what ran out is the caller's own budget.
        slow = make_model("slow", tokens_per_second=10)
        h = build_use_case(
            budgets=[exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID)],
            default_policy=BudgetPolicy.DOWNGRADE,
            downgrade=[slow],
        )

        with pytest.raises(BudgetExhaustedError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.scope is BudgetScope.CLIENT
        assert h.generation.calls == []

    def test_a_target_among_the_requests_own_candidates_is_passed_over(self) -> None:
        h = build_use_case(
            budgets=[exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID)],
            default_policy=BudgetPolicy.DOWNGRADE,
            downgrade=[HAIKU, SONNET],
            script={SONNET.id.value: [ok()]},
        )

        result = h.use_case.execute(make_cmd())

        assert (result.model, result.downgraded) == ("claude-sonnet-4-6", True)
        assert h.generation.called_models() == ["claude-sonnet-4-6"]

    def test_the_requested_model_as_the_only_target_is_no_downgrade(self) -> None:
        # Serving haiku again from the downgrade pool would only be a second budget for it.
        h = build_use_case(
            budgets=[exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID)],
            default_policy=BudgetPolicy.DOWNGRADE,
            downgrade=[HAIKU],
        )

        with pytest.raises(BudgetExhaustedError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.scope is BudgetScope.CLIENT
        assert h.generation.calls == []

    def test_a_downgraded_answer_is_recorded_as_such(self) -> None:
        h = build_use_case(
            budgets=[exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID)],
            default_policy=BudgetPolicy.DOWNGRADE,
            downgrade=[SONNET],
            script={SONNET.id.value: [ok()]},
        )

        h.use_case.execute(make_cmd())

        [record] = h.usage.added
        assert (record.model, record.downgraded) == (SONNET.id, True)

    def test_running_out_of_time_is_answered_about_the_model_the_caller_asked_for(self) -> None:
        # Four budget reads of 4 s leave 9 s, short of the target's 10 — no attempt starts. The
        # advice must be about the requested model: the target is one the caller never named.
        quick = make_model("quick", tokens_per_second=200)
        h = build_use_case(
            routes={"fast": [quick]},
            budgets=[exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID)],
            default_policy=BudgetPolicy.DOWNGRADE,
            downgrade=[FALLBACK],
            budget_read_seconds=4.0,
        )

        with pytest.raises(RequestTooSlowForSyncError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.details_dict() == {"max_tokens_allowed": 1000, "budget_seconds": 9.0}
        assert h.generation.calls == []

    def test_a_provider_shared_with_the_target_is_read_once(self) -> None:
        h = build_use_case(
            budgets=[exhausted_budget(BudgetScope.CLIENT, _CLIENT_ID)],
            default_policy=BudgetPolicy.DOWNGRADE,
            downgrade=[SONNET],
            script={SONNET.id.value: [ok()]},
        )

        h.use_case.execute(make_cmd())

        assert h.budgets.reads == [
            (BudgetScope.PROVIDER, "anthropic"),
            (BudgetScope.CLIENT, CLIENT),
            (BudgetScope.CLIENT_DOWNGRADE, CLIENT),
        ]


class TestTransactions:
    def test_budget_reads_and_the_record_each_take_one_transaction(self) -> None:
        # The provider fake fails any call made inside an open transaction, so passing also pins
        # that the budget transaction is closed before the provider is called.
        h = build_use_case()
        h.use_case.execute(make_cmd())
        assert (h.uow.commits, h.uow.rollbacks) == (2, 0)

    def test_unavailable_storage_passes_through(self) -> None:
        h = build_use_case(budget_error=StorageUnavailableError())
        with pytest.raises(StorageUnavailableError):
            h.use_case.execute(make_cmd())
        assert h.generation.calls == []

    def test_a_cancelled_aggregate_passes_through(self) -> None:
        h = build_use_case(budget_error=ConcurrentUpdateError())
        with pytest.raises(ConcurrentUpdateError):
            h.use_case.execute(make_cmd())
        assert h.generation.calls == []

    def test_a_missing_grant_passes_through(self) -> None:
        h = build_use_case(budget_error=IntegrityError())
        with pytest.raises(IntegrityError):
            h.use_case.execute(make_cmd())
        assert h.generation.calls == []
