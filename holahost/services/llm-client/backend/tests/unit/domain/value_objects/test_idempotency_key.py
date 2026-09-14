import pytest

from domain.exceptions import DomainValidationError
from domain.value_objects.idempotency_key import MAX_IDEMPOTENCY_KEY_LENGTH, IdempotencyKey


class TestIdempotencyKey:
    def test_holds_the_value_verbatim(self) -> None:
        assert IdempotencyKey(" 7c1f ").value == " 7c1f "

    def test_accepts_a_single_character(self) -> None:
        assert IdempotencyKey("a").value == "a"

    def test_accepts_the_maximum_length(self) -> None:
        key = "k" * MAX_IDEMPOTENCY_KEY_LENGTH
        assert IdempotencyKey(key).value == key

    def test_rejects_an_empty_key(self) -> None:
        with pytest.raises(DomainValidationError, match="length") as exc:
            IdempotencyKey("")
        assert exc.value.field == "idempotency_key"

    def test_rejects_a_key_over_the_maximum_length(self) -> None:
        too_long = "k" * (MAX_IDEMPOTENCY_KEY_LENGTH + 1)
        with pytest.raises(DomainValidationError, match="length") as exc:
            IdempotencyKey(too_long)
        assert exc.value.field == "idempotency_key"
        assert too_long not in str(exc.value)

    def test_maximum_length_is_128(self) -> None:
        assert MAX_IDEMPOTENCY_KEY_LENGTH == 128
