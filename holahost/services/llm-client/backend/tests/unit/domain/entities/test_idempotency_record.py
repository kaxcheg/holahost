from datetime import UTC, datetime, timedelta

import pytest

from domain.entities.idempotency_record import IdempotencyRecord
from domain.exceptions import DomainValidationError
from domain.value_objects.client_id import ClientId
from domain.value_objects.idempotency_key import IdempotencyKey
from domain.value_objects.idempotency_state import IdempotencyState
from domain.value_objects.token_count import TokenCount
from domain.value_objects.usage import Usage

_CLIENT = ClientId("guest-reply-cli")
_KEY = IdempotencyKey("7c1f")
_TTL = timedelta(minutes=15)
_USAGE = Usage(input_tokens=TokenCount(1240), output_tokens=TokenCount(310))


class TestIdempotencyRecord:
    def test_create_claims_the_key_in_flight_without_usage(self) -> None:
        record = IdempotencyRecord.create(_CLIENT, _KEY, _TTL)
        assert record.client_id == _CLIENT
        assert record.key == _KEY
        assert record.state is IdempotencyState.IN_FLIGHT
        assert record.usage is None

    def test_create_expires_after_the_ttl(self) -> None:
        before = datetime.now(tz=UTC)
        record = IdempotencyRecord.create(_CLIENT, _KEY, _TTL)
        after = datetime.now(tz=UTC)
        assert before + _TTL <= record.expires_at <= after + _TTL

    def test_complete_moves_to_completed_and_keeps_usage(self) -> None:
        record = IdempotencyRecord.create(_CLIENT, _KEY, _TTL)
        record.complete(_USAGE)
        assert record.state is IdempotencyState.COMPLETED
        assert record.usage == _USAGE

    def test_complete_rejects_a_completed_record(self) -> None:
        record = IdempotencyRecord.create(_CLIENT, _KEY, _TTL)
        record.complete(_USAGE)
        with pytest.raises(DomainValidationError, match="already completed") as exc:
            record.complete(_USAGE)
        assert exc.value.field is None

    def test_rejects_an_in_flight_record_with_usage(self) -> None:
        with pytest.raises(DomainValidationError, match="usage") as exc:
            IdempotencyRecord(
                client_id=_CLIENT,
                key=_KEY,
                state=IdempotencyState.IN_FLIGHT,
                usage=_USAGE,
                expires_at=datetime.now(tz=UTC) + _TTL,
            )
        assert exc.value.field is None

    def test_rejects_a_completed_record_without_usage(self) -> None:
        with pytest.raises(DomainValidationError, match="usage") as exc:
            IdempotencyRecord(
                client_id=_CLIENT,
                key=_KEY,
                state=IdempotencyState.COMPLETED,
                usage=None,
                expires_at=datetime.now(tz=UTC) + _TTL,
            )
        assert exc.value.field is None

    def test_not_expired_within_the_ttl(self) -> None:
        assert IdempotencyRecord.create(_CLIENT, _KEY, _TTL).is_expired() is False

    def test_expired_once_the_ttl_has_run_out(self) -> None:
        assert IdempotencyRecord.create(_CLIENT, _KEY, timedelta(0)).is_expired() is True

    def test_equal_when_same_client_and_key_regardless_of_state(self) -> None:
        completed = IdempotencyRecord.create(_CLIENT, _KEY, _TTL)
        completed.complete(_USAGE)
        assert IdempotencyRecord.create(_CLIENT, _KEY, _TTL) == completed

    def test_not_equal_across_keys_clients_or_types(self) -> None:
        record = IdempotencyRecord.create(_CLIENT, _KEY, _TTL)
        assert record != IdempotencyRecord.create(_CLIENT, IdempotencyKey("other"), _TTL)
        assert record != IdempotencyRecord.create(ClientId("other-client"), _KEY, _TTL)
        assert record != object()

    def test_hashable_by_client_and_key(self) -> None:
        a = IdempotencyRecord.create(_CLIENT, _KEY, _TTL)
        b = IdempotencyRecord.create(_CLIENT, _KEY, _TTL)
        b.complete(_USAGE)
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
