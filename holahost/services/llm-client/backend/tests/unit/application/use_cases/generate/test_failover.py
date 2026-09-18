"""GenerateUseCase: moving to the next candidate model when one cannot answer.

`fast` resolves to haiku (anthropic) and then to a model of another vendor. Every scripted call
takes one second; the deadline is 25 s after the start.
"""

from __future__ import annotations

import pytest
from tests._support.builders import (
    CLIENT,
    FALLBACK,
    HAIKU,
    OTHER_VENDOR,
    SONNET,
    exhausted_budget,
    make_cmd,
    make_model,
    make_usage,
)
from tests._support.generate import build_use_case, fails, ok

from application.exceptions import ContentRefusedError, RequestTooSlowForSyncError, UpstreamLlmError
from application.ports.exceptions import (
    ProviderRefusedContentError,
    ProviderRejectedRequestError,
    TransientProviderError,
)
from domain.value_objects.budget_scope import BudgetScope

_CHAIN = {"fast": [HAIKU, FALLBACK]}


def _overloaded() -> TransientProviderError:
    return TransientProviderError("overloaded", status=529, retry_after=None)


class TestMovingOn:
    def test_exhausted_attempts_move_to_the_next_candidate(self) -> None:
        h = build_use_case(
            routes=_CHAIN,
            script={
                HAIKU.id.value: [fails(_overloaded()), fails(_overloaded())],
                FALLBACK.id.value: [ok()],
            },
        )

        result = h.use_case.execute(make_cmd())

        assert (result.provider, result.model) == ("other-vendor", "other-vendor-mini")
        assert (result.failed_over, result.attempts) == (True, 3)
        assert h.usage.added[0].failed_over is True

    def test_a_rejected_request_moves_on_without_a_pause(self) -> None:
        h = build_use_case(
            routes=_CHAIN,
            script={
                HAIKU.id.value: [fails(ProviderRejectedRequestError("revoked", status=401))],
                FALLBACK.id.value: [ok()],
            },
        )

        result = h.use_case.execute(make_cmd())

        assert result.failed_over is True
        assert h.clock.sleeps == []

    def test_a_refusal_does_not_move_on(self) -> None:
        h = build_use_case(
            routes=_CHAIN,
            script={HAIKU.id.value: [fails(ProviderRefusedContentError(usage=make_usage()))]},
        )

        with pytest.raises(ContentRefusedError):
            h.use_case.execute(make_cmd())

        assert h.generation.called_models() == ["claude-haiku-4-5"]


class TestWhenNoCandidateAnswers:
    def test_only_rejections_raise_the_last_rejection(self) -> None:
        h = build_use_case(
            routes=_CHAIN,
            script={
                HAIKU.id.value: [fails(ProviderRejectedRequestError("revoked", status=401))],
                FALLBACK.id.value: [fails(ProviderRejectedRequestError("no access", status=403))],
            },
        )

        with pytest.raises(ProviderRejectedRequestError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.status == 403

    def test_a_transient_failure_anywhere_makes_it_an_upstream_error(self) -> None:
        h = build_use_case(
            routes=_CHAIN,
            script={
                HAIKU.id.value: [fails(_overloaded()), fails(_overloaded())],
                FALLBACK.id.value: [fails(ProviderRejectedRequestError("no access", status=403))],
            },
        )

        with pytest.raises(UpstreamLlmError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.attempts == 3

    def test_no_attempt_started_is_too_slow_not_an_upstream_error(self) -> None:
        # Two budget reads of 8 s each leave 9 s, short of haiku's 10 s: the provider is never
        # called, so blaming it would be false.
        h = build_use_case(budget_read_seconds=8.0)

        with pytest.raises(RequestTooSlowForSyncError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.details_dict() == {"max_tokens_allowed": 900, "budget_seconds": 9.0}
        assert h.generation.calls == []


class TestSkippingACandidate:
    def test_a_candidate_too_small_for_the_request_is_skipped(self) -> None:
        small = make_model(
            "other-vendor-mini", provider=OTHER_VENDOR, max_context=1050, max_output=1000
        )
        h = build_use_case(
            routes={"fast": [HAIKU, small]},
            script={HAIKU.id.value: [fails(_overloaded()), fails(_overloaded())]},
        )

        with pytest.raises(UpstreamLlmError):
            h.use_case.execute(make_cmd())

        assert h.generation.called_models() == ["claude-haiku-4-5", "claude-haiku-4-5"]

    def test_a_candidate_whose_provider_is_exhausted_is_skipped(self) -> None:
        h = build_use_case(
            routes=_CHAIN,
            budgets=[exhausted_budget(BudgetScope.PROVIDER, OTHER_VENDOR.name)],
            script={HAIKU.id.value: [fails(_overloaded()), fails(_overloaded())]},
        )

        with pytest.raises(UpstreamLlmError):
            h.use_case.execute(make_cmd())

        assert FALLBACK.id.value not in h.generation.called_models()


class TestCandidateBudgets:
    def test_a_candidates_provider_is_read_only_when_it_is_needed(self) -> None:
        h = build_use_case(routes=_CHAIN)
        h.use_case.execute(make_cmd())
        assert (BudgetScope.PROVIDER, "other-vendor") not in h.budgets.reads

    def test_a_candidates_provider_is_read_in_a_transaction_of_its_own(self) -> None:
        h = build_use_case(
            routes=_CHAIN,
            script={
                HAIKU.id.value: [fails(_overloaded()), fails(_overloaded())],
                FALLBACK.id.value: [ok()],
            },
        )

        h.use_case.execute(make_cmd())

        assert h.budgets.reads == [
            (BudgetScope.PROVIDER, "anthropic"),
            (BudgetScope.CLIENT, CLIENT),
            (BudgetScope.PROVIDER, "other-vendor"),
        ]
        assert h.uow.commits == 3

    def test_a_provider_already_read_is_not_read_again(self) -> None:
        h = build_use_case(
            routes={"fast": [HAIKU, SONNET]},
            script={
                HAIKU.id.value: [fails(_overloaded()), fails(_overloaded())],
                SONNET.id.value: [ok()],
            },
        )

        result = h.use_case.execute(make_cmd())

        assert (result.model, result.failed_over) == ("claude-sonnet-4-6", True)
        assert h.budgets.reads == [
            (BudgetScope.PROVIDER, "anthropic"),
            (BudgetScope.CLIENT, CLIENT),
        ]
