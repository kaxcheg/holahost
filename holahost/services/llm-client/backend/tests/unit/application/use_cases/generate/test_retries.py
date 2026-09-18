"""GenerateUseCase: repeats at one model, all under one request deadline.

The clock starts at 1000 and the deadline is 25 s later. Haiku needs 10 s for a full answer
(1000 tokens at 100 tokens/s); every scripted call moves the clock by its own duration.
"""

from __future__ import annotations

import pytest
from tests._support.builders import HAIKU, make_cmd, make_model, make_usage
from tests._support.generate import build_use_case, fails, ok

from application.exceptions import ContentRefusedError, UpstreamLlmError
from application.ports.exceptions import (
    ProviderRefusedContentError,
    ProviderRejectedRequestError,
    TransientProviderError,
)


def _overloaded(
    status: int | None = 529, retry_after: float | None = None
) -> TransientProviderError:
    return TransientProviderError("overloaded", status=status, retry_after=retry_after)


class TestBackoff:
    def test_a_transient_failure_is_repeated_after_the_base_pause(self) -> None:
        h = build_use_case(script={HAIKU.id.value: [fails(_overloaded(), 2.0), ok(1.0)]})

        result = h.use_case.execute(make_cmd())

        assert h.clock.sleeps == [1.0]
        assert (result.attempts, result.provider_ms) == (2, 3000)

    def test_the_pause_varies_down_by_the_jitter(self) -> None:
        h = build_use_case(script={HAIKU.id.value: [fails(_overloaded()), ok()]}, random_value=0.0)
        h.use_case.execute(make_cmd())
        assert h.clock.sleeps == [pytest.approx(0.8)]

    def test_the_pause_varies_up_by_the_jitter(self) -> None:
        h = build_use_case(script={HAIKU.id.value: [fails(_overloaded()), ok()]}, random_value=1.0)
        h.use_case.execute(make_cmd())
        assert h.clock.sleeps == [pytest.approx(1.2)]

    def test_the_providers_retry_after_wins(self) -> None:
        h = build_use_case(script={HAIKU.id.value: [fails(_overloaded(retry_after=3.0)), ok()]})
        h.use_case.execute(make_cmd())
        assert h.clock.sleeps == [3.0]


class TestAttempts:
    def test_attempts_at_one_model_are_bounded(self) -> None:
        h = build_use_case(
            script={HAIKU.id.value: [fails(_overloaded(529)), fails(_overloaded(503))]}
        )

        with pytest.raises(UpstreamLlmError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.details_dict() == {"attempts": 2, "upstream_status": 503}
        assert h.clock.sleeps == [1.0]  # no pause after the last attempt

    def test_a_timeout_reports_no_upstream_status(self) -> None:
        h = build_use_case(
            script={HAIKU.id.value: [fails(_overloaded(None)), fails(_overloaded(None))]}
        )
        with pytest.raises(UpstreamLlmError) as exc:
            h.use_case.execute(make_cmd())
        assert exc.value.upstream_status is None

    def test_a_rejected_request_is_not_repeated(self) -> None:
        h = build_use_case(
            script={HAIKU.id.value: [fails(ProviderRejectedRequestError("revoked", status=401))]}
        )
        with pytest.raises(ProviderRejectedRequestError):
            h.use_case.execute(make_cmd())
        assert (len(h.generation.calls), h.clock.sleeps) == (1, [])

    def test_a_refusal_is_not_repeated(self) -> None:
        h = build_use_case(
            script={HAIKU.id.value: [fails(ProviderRefusedContentError(usage=make_usage()))]}
        )
        with pytest.raises(ContentRefusedError):
            h.use_case.execute(make_cmd())
        assert (len(h.generation.calls), h.clock.sleeps) == (1, [])


class TestTheDeadline:
    def test_an_attempt_times_out_no_later_than_the_deadline(self) -> None:
        quick = make_model("quick", tokens_per_second=1000)  # a full answer takes 1 s
        h = build_use_case(
            routes={"fast": [quick]},
            script={"quick": [fails(_overloaded(None), 20.0), ok(1.0)]},
        )

        h.use_case.execute(make_cmd())

        # 20 s spent, 1 s paused: 4 s remain for the second attempt.
        assert [call.timeout_s for call in h.generation.calls] == [20.0, 4.0]

    def test_no_repeat_when_a_full_answer_no_longer_fits(self) -> None:
        h = build_use_case(script={HAIKU.id.value: [fails(_overloaded(None), 20.0)]})

        with pytest.raises(UpstreamLlmError) as exc:
            h.use_case.execute(make_cmd())

        # 5 s remain; the pause plus 10 s of generation do not fit, so nothing is slept either.
        assert exc.value.attempts == 1
        assert h.clock.sleeps == []

    def test_a_retry_after_beyond_the_deadline_is_not_waited_out(self) -> None:
        h = build_use_case(script={HAIKU.id.value: [fails(_overloaded(retry_after=30.0))]})

        with pytest.raises(UpstreamLlmError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.attempts == 1
        assert h.clock.sleeps == []
