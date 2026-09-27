"""GenerateUseCase: the usage record — what it carries, when it is written, how a write failure
surfaces."""

from __future__ import annotations

import pytest
from tests._support.builders import ANTHROPIC, CLIENT, HAIKU, make_cmd, make_generation, make_usage
from tests._support.generate import build_use_case, fails, ok

from application.exceptions import ContentRefusedError, UpstreamLlmError, UsageNotRecordedError
from application.ports.exceptions import (
    ConcurrentUpdateError,
    IntegrityError,
    ProviderRefusedContentError,
    StorageUnavailableError,
    TransientProviderError,
)
from domain.value_objects.client_id import ClientId
from domain.value_objects.subject import Subject


def _overloaded() -> TransientProviderError:
    return TransientProviderError("overloaded", status=529, retry_after=None)


class TestTheRecord:
    def test_carries_what_answered_and_who_asked(self) -> None:
        answer = make_generation(usage=make_usage(120, 30))
        h = build_use_case(script={HAIKU.id.value: [ok(1.5, generation=answer)]})

        h.use_case.execute(make_cmd(request_id="req-7"))

        [record] = h.usage.added
        assert record.request_id == "req-7"
        assert (record.client_id, record.subject) == (ClientId(CLIENT), Subject(CLIENT))
        assert (record.provider, record.model) == (ANTHROPIC.name, HAIKU.id)
        assert record.usage == make_usage(120, 30)
        assert record.latency_ms == 1500
        assert (record.downgraded, record.failed_over) == (False, False)

    def test_latency_is_the_answering_attempts_alone(self) -> None:
        h = build_use_case(script={HAIKU.id.value: [fails(_overloaded(), 2.0), ok(1.5)]})

        result = h.use_case.execute(make_cmd())

        assert h.usage.added[0].latency_ms == 1500
        assert result.provider_ms == 3500

    def test_a_refusal_is_recorded_with_the_confirmed_usage(self) -> None:
        h = build_use_case(
            script={
                HAIKU.id.value: [fails(ProviderRefusedContentError(usage=make_usage(40, 0)), 0.5)]
            }
        )

        with pytest.raises(ContentRefusedError) as exc:
            h.use_case.execute(make_cmd())

        assert exc.value.details_dict() == {"provider": "anthropic", "model": "claude-haiku-4-5"}
        [record] = h.usage.added
        assert (record.usage, record.latency_ms) == (make_usage(40, 0), 500)

    def test_nothing_is_recorded_without_confirmed_usage(self) -> None:
        h = build_use_case(script={HAIKU.id.value: [fails(_overloaded()), fails(_overloaded())]})

        with pytest.raises(UpstreamLlmError):
            h.use_case.execute(make_cmd())

        assert h.usage.added == []


class TestWritingTheRecord:
    def test_a_conflict_is_retried_because_the_insert_is_idempotent(self) -> None:
        h = build_use_case(usage_errors=[ConcurrentUpdateError()])

        h.use_case.execute(make_cmd())

        assert (len(h.usage.added), h.usage.calls) == (1, 2)
        assert h.uow.rollbacks == 1

    def test_a_failed_write_is_raised_with_the_confirmed_spend(self) -> None:
        answer = make_generation(usage=make_usage(120, 30))
        h = build_use_case(
            script={HAIKU.id.value: [ok(generation=answer)]},
            usage_errors=[StorageUnavailableError()],
        )

        with pytest.raises(UsageNotRecordedError) as exc:
            h.use_case.execute(make_cmd())

        assert (exc.value.input_tokens, exc.value.output_tokens) == (120, 30)
        assert (exc.value.provider, exc.value.model) == ("anthropic", "claude-haiku-4-5")
        assert isinstance(exc.value.__cause__, StorageUnavailableError)
        assert str(exc.value) == "usage not recorded: StorageUnavailableError"
        assert h.usage.added == []

    def test_conflicts_past_the_retries_are_raised_the_same_way(self) -> None:
        h = build_use_case(usage_errors=[ConcurrentUpdateError()] * 3)

        with pytest.raises(UsageNotRecordedError) as exc:
            h.use_case.execute(make_cmd())

        assert isinstance(exc.value.__cause__, ConcurrentUpdateError)
        assert h.usage.calls == 3

    def test_an_integrity_error_is_a_defect_and_not_retried(self) -> None:
        h = build_use_case(usage_errors=[IntegrityError()])

        with pytest.raises(UsageNotRecordedError) as exc:
            h.use_case.execute(make_cmd())

        assert isinstance(exc.value.__cause__, IntegrityError)
        assert h.usage.calls == 1
