"""GenerateUseCase: the context and pre-flight checks refuse before any budget read or any call.

The default command's input estimate is 72: "You answer guests." (18 bytes) and "What time is
check-in?" (22 bytes), each with 16 framing tokens.
"""

from __future__ import annotations

import pytest
from tests._support.builders import CLIENT, make_cmd, make_model
from tests._support.generate import build_use_case, ok

from application.exceptions import ContextOverflowError, RequestTooSlowForSyncError

_INPUT_ESTIMATE = 72


class TestMaxTokens:
    def test_a_request_above_the_ceiling_is_truncated(self) -> None:
        h = build_use_case()
        h.use_case.execute(make_cmd(max_tokens=5000))
        assert h.generation.calls[0].max_tokens == 1000

    def test_no_request_means_the_ceiling(self) -> None:
        h = build_use_case()
        h.use_case.execute(make_cmd(max_tokens=None))
        assert h.generation.calls[0].max_tokens == 1000

    def test_a_smaller_request_is_kept(self) -> None:
        h = build_use_case()
        h.use_case.execute(make_cmd(max_tokens=200))
        assert h.generation.calls[0].max_tokens == 200


class TestContext:
    def test_the_input_estimate_plus_max_tokens_must_fit(self) -> None:
        tiny = make_model("tiny", max_context=_INPUT_ESTIMATE + 999, max_output=1000)
        h = build_use_case(routes={"fast": [tiny]})

        with pytest.raises(ContextOverflowError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.details_dict() == {
            "max_context": _INPUT_ESTIMATE + 999,
            "estimated": _INPUT_ESTIMATE + 1000,
        }
        assert h.budgets.reads == []
        assert h.generation.calls == []

    def test_an_exact_fit_is_accepted(self) -> None:
        tiny = make_model("tiny", max_context=_INPUT_ESTIMATE + 1000, max_output=1000)
        h = build_use_case(routes={"fast": [tiny]}, script={"tiny": [ok()]})
        assert h.use_case.execute(make_cmd()).model == "tiny"


class TestPreflight:
    def test_a_full_answer_that_cannot_finish_in_time_is_refused(self) -> None:
        slow = make_model("slow", tokens_per_second=10)  # 1000 tokens take 100 s against 25 s
        h = build_use_case(routes={"fast": [slow]})

        with pytest.raises(RequestTooSlowForSyncError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.details_dict() == {"max_tokens_allowed": 200, "budget_seconds": 20.0}
        assert h.budgets.reads == []
        assert h.generation.calls == []

    def test_an_answer_longer_than_one_attempt_is_refused(self) -> None:
        # 1000 tokens in 25 s: within the request budget, but no single attempt may run past the
        # 20 s provider timeout, so the call would be cut off after being paid for.
        slow = make_model("slow", tokens_per_second=40)
        h = build_use_case(routes={"fast": [slow]}, script={"slow": [ok()]})

        with pytest.raises(RequestTooSlowForSyncError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.details_dict() == {"max_tokens_allowed": 800, "budget_seconds": 20.0}
        assert h.generation.calls == []

    def test_an_answer_filling_one_whole_attempt_is_accepted(self) -> None:
        slow = make_model("slow", tokens_per_second=50)  # 1000 tokens in exactly 20 s
        h = build_use_case(routes={"fast": [slow]}, script={"slow": [ok()]})
        assert h.use_case.execute(make_cmd()).model == "slow"

    def test_a_smaller_max_tokens_makes_it_fit(self) -> None:
        slow = make_model("slow", tokens_per_second=10)
        h = build_use_case(routes={"fast": [slow]}, script={"slow": [ok()]})
        assert h.use_case.execute(make_cmd(max_tokens=200)).model == "slow"


class TestChecksRunAfterTheKeyIsClaimed:
    def test_a_refused_check_releases_the_key(self) -> None:
        tiny = make_model("tiny", max_context=1001, max_output=1000)
        h = build_use_case(routes={"fast": [tiny]})

        with pytest.raises(ContextOverflowError):
            h.use_case.execute(make_cmd(idempotency_key="k-1"))

        assert h.idempotency.begun == [(CLIENT, "k-1")]
        assert h.idempotency.released == [(CLIENT, "k-1")]
