"""The `IdempotencyRecord` entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from domain.exceptions import DomainValidationError
from domain.value_objects.client_id import ClientId
from domain.value_objects.idempotency_key import IdempotencyKey
from domain.value_objects.idempotency_state import IdempotencyState
from domain.value_objects.usage import Usage


@dataclass(eq=False)
class IdempotencyRecord:
    """Remembers that a client's request with a given key is in flight or already done.

    Identified by `(client_id, key)` — different clients' keys never collide. The only transition
    is `in_flight → completed`. A completed record keeps `usage` and nothing else: a repeat on the
    key is answered with a conflict, never with the first answer, whose text is stored nowhere.

    Mutable, because `complete` moves it on in place.

    :param client_id: The client that sent the key.
    :param key: The key.
    :param state: `in_flight` until the generation finishes, then `completed`.
    :param usage: `None` while in flight; the generation's usage once completed.
    :param expires_at: UTC; from this moment the key is no longer recognised.
    """

    client_id: ClientId
    key: IdempotencyKey
    state: IdempotencyState
    usage: Usage | None
    expires_at: datetime

    def __post_init__(self) -> None:
        # The store's own bookkeeping, not request data — `field` stays None.
        if (self.state is IdempotencyState.IN_FLIGHT) != (self.usage is None):
            raise DomainValidationError(
                "IdempotencyRecord usage must be set exactly when it is completed"
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IdempotencyRecord):
            return NotImplemented
        return (self.client_id, self.key) == (other.client_id, other.key)

    def __hash__(self) -> int:
        return hash((self.client_id, self.key))

    @classmethod
    def create(cls, client_id: ClientId, key: IdempotencyKey, ttl: timedelta) -> IdempotencyRecord:
        """Claim a key for a request that has just been accepted."""
        return cls(
            client_id=client_id,
            key=key,
            state=IdempotencyState.IN_FLIGHT,
            usage=None,
            expires_at=datetime.now(tz=UTC) + ttl,
        )

    def complete(self, usage: Usage) -> None:
        """Mark the request finished and keep its usage.

        :raises DomainValidationError: the record is already completed — with `field` unset: a key
            is completed once, so a second completion is a defect.
        """
        if self.state is IdempotencyState.COMPLETED:
            raise DomainValidationError("IdempotencyRecord is already completed")
        self.state = IdempotencyState.COMPLETED
        self.usage = usage

    def is_expired(self) -> bool:
        """Whether the key's TTL has run out."""
        return datetime.now(tz=UTC) >= self.expires_at
