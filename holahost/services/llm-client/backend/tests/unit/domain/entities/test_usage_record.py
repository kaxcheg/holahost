import dataclasses
from datetime import UTC, datetime

import pytest

from domain.entities.usage_record import UsageRecord
from domain.exceptions import DomainValidationError
from domain.value_objects.client_id import ClientId
from domain.value_objects.generation_id import GenerationId
from domain.value_objects.model_id import ModelId
from domain.value_objects.provider_name import ProviderName
from domain.value_objects.subject import Subject
from domain.value_objects.token_count import TokenCount
from domain.value_objects.usage import Usage

_USAGE = Usage(input_tokens=TokenCount(1240), output_tokens=TokenCount(310))


def _create(
    *, latency_ms: int = 1800, downgraded: bool = False, failed_over: bool = False
) -> UsageRecord:
    return UsageRecord.create(
        request_id="req-1",
        client_id=ClientId("guest-reply-cli"),
        subject=Subject("guest-reply-cli"),
        provider=ProviderName("anthropic"),
        model=ModelId("claude-haiku-4-5"),
        usage=_USAGE,
        latency_ms=latency_ms,
        downgraded=downgraded,
        failed_over=failed_over,
    )


def _with_id(generation_id: GenerationId, *, request_id: str = "req-1") -> UsageRecord:
    return UsageRecord(
        id=generation_id,
        request_id=request_id,
        client_id=ClientId("guest-reply-cli"),
        subject=Subject("guest-reply-cli"),
        provider=ProviderName("anthropic"),
        model=ModelId("claude-haiku-4-5"),
        usage=_USAGE,
        latency_ms=1800,
        downgraded=False,
        failed_over=False,
        created_at=datetime(2026, 9, 13, tzinfo=UTC),
    )


class TestUsageRecord:
    def test_create_sets_fields(self) -> None:
        record = _create(downgraded=True, failed_over=True)
        assert record.request_id == "req-1"
        assert record.client_id == ClientId("guest-reply-cli")
        assert record.subject == Subject("guest-reply-cli")
        assert record.provider == ProviderName("anthropic")
        assert record.model == ModelId("claude-haiku-4-5")
        assert record.usage == _USAGE
        assert record.latency_ms == 1800
        assert record.downgraded is True
        assert record.failed_over is True

    def test_create_generates_a_distinct_id_per_record(self) -> None:
        assert _create().id != _create().id

    def test_create_stamps_the_current_utc_time(self) -> None:
        before = datetime.now(tz=UTC)
        record = _create()
        after = datetime.now(tz=UTC)
        assert before <= record.created_at <= after
        assert record.created_at.tzinfo is UTC

    def test_accepts_zero_latency(self) -> None:
        assert _create(latency_ms=0).latency_ms == 0

    def test_rejects_a_negative_latency(self) -> None:
        with pytest.raises(DomainValidationError, match="latency_ms") as exc:
            _create(latency_ms=-1)
        assert exc.value.field is None

    def test_is_immutable(self) -> None:
        record = _create()
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.latency_ms = 1  # type: ignore[misc]

    def test_equal_when_same_id_regardless_of_other_fields(self) -> None:
        generation_id = GenerationId.new()
        assert _with_id(generation_id) == _with_id(generation_id, request_id="req-2")

    def test_not_equal_when_different_id_or_other_type(self) -> None:
        assert _with_id(GenerationId.new()) != _with_id(GenerationId.new())
        assert _create() != object()

    def test_hashable_by_id(self) -> None:
        generation_id = GenerationId.new()
        a = _with_id(generation_id)
        b = _with_id(generation_id, request_id="req-2")
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
