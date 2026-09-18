"""Port for the store of idempotency keys."""

from __future__ import annotations

from typing import Protocol

from domain.value_objects.client_id import ClientId
from domain.value_objects.idempotency_key import IdempotencyKey
from domain.value_objects.usage import Usage


class IdempotencyStore(Protocol):
    """Remembers, per client, the keys of requests in flight or finished, so a repeat is not paid
    for twice.

    Concurrency: implementations are called from every thread of the pool, and one lock guards all
    three methods. A record past its TTL counts as absent.
    """

    def begin(self, client_id: ClientId, key: IdempotencyKey) -> None:
        """Claim `key` for a request that has just been accepted.

        The check and the claim are one atomic step: separated, two parallel repeats would both pass
        and both pay for the generation.

        :param client_id: The client; different clients' keys never collide.
        :param key: The key the request carries.
        :raises DuplicateRequestError: the key is already held, in flight or completed.
        """
        ...

    def complete(self, client_id: ClientId, key: IdempotencyKey, usage: Usage) -> None:
        """Mark a claimed key finished, keeping the spend — a repeat is told it is completed.

        A key no longer held (its TTL ran out) is ignored.
        """
        ...

    def release(self, client_id: ClientId, key: IdempotencyKey) -> None:
        """Drop a claim whose request failed, so an honest repeat may pass.

        A key no longer held is ignored.
        """
        ...
