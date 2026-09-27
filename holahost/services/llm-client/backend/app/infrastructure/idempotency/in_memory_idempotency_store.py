"""`IdempotencyStore` in process memory: the protection holds for one process's life."""

from __future__ import annotations

import threading
from datetime import timedelta

from application.exceptions import DuplicateRequestError
from domain.entities.idempotency_record import IdempotencyRecord
from domain.value_objects.client_id import ClientId
from domain.value_objects.idempotency_key import IdempotencyKey
from domain.value_objects.idempotency_state import IdempotencyState
from domain.value_objects.usage import Usage

_Identity = tuple[ClientId, IdempotencyKey]


class InMemoryIdempotencyStore:
    """Records by `(client_id, key)`, with all three methods under one lock.

    Every record lives the same `ttl`, so insertion order is expiry order: each `begin` drops the
    expired ones from the front, and memory stays bounded by one TTL's traffic. No cap evicts a live
    record — that would quietly lift the protection against paying twice.
    """

    def __init__(self, ttl: timedelta) -> None:
        self._ttl = ttl
        self._records: dict[_Identity, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def begin(self, client_id: ClientId, key: IdempotencyKey) -> None:
        identity = (client_id, key)
        with self._lock:
            self._drop_expired()
            held = self._live(identity)
            if held is not None:
                raise DuplicateRequestError(state=held.state)
            # An expired record still here is re-inserted at the end, keeping expiry order.
            self._records.pop(identity, None)
            self._records[identity] = IdempotencyRecord.create(client_id, key, self._ttl)

    def complete(self, client_id: ClientId, key: IdempotencyKey, usage: Usage) -> None:
        with self._lock:
            record = self._live((client_id, key))
            if record is not None and record.state is IdempotencyState.IN_FLIGHT:
                record.complete(usage)

    def release(self, client_id: ClientId, key: IdempotencyKey) -> None:
        # A completed key is never dropped: the provider charged for it, and a repeat would pay
        # again.
        with self._lock:
            record = self._live((client_id, key))
            if record is not None and record.state is IdempotencyState.IN_FLIGHT:
                del self._records[(client_id, key)]

    def _live(self, identity: _Identity) -> IdempotencyRecord | None:
        record = self._records.get(identity)
        return None if record is None or record.is_expired() else record

    def _drop_expired(self) -> None:
        while self._records:
            identity, record = next(iter(self._records.items()))
            if not record.is_expired():
                return
            del self._records[identity]
