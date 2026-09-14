"""The caller's idempotency key."""

from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainValidationError

MAX_IDEMPOTENCY_KEY_LENGTH = 128


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """The `Idempotency-Key` header's value — 1..MAX_IDEMPOTENCY_KEY_LENGTH characters.

    Opaque: compared verbatim, never stripped. Uniqueness per client within the key's TTL is the
    idempotency store's to enforce, not a property of one value.

    :param value: The key, as the caller sent it.
    """

    value: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.value) <= MAX_IDEMPOTENCY_KEY_LENGTH:
            raise DomainValidationError(
                f"IdempotencyKey length must be 1..{MAX_IDEMPOTENCY_KEY_LENGTH}",
                field="idempotency_key",
            )
