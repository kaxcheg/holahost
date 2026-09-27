"""`InMemoryIdempotencyStore`: one claim per client and key, kept for its TTL."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from tests._support.builders import make_usage

from application.exceptions import DuplicateRequestError
from domain.value_objects.client_id import ClientId
from domain.value_objects.idempotency_key import IdempotencyKey
from domain.value_objects.idempotency_state import IdempotencyState
from infrastructure.idempotency.in_memory_idempotency_store import InMemoryIdempotencyStore

_TTL = timedelta(minutes=15)
_EXPIRED = timedelta(0)
_CLIENT = ClientId("cli-1")
_KEY = IdempotencyKey("k-1")


class TestClaiming:
    def test_a_key_in_flight_is_a_duplicate(self) -> None:
        store = InMemoryIdempotencyStore(_TTL)
        store.begin(_CLIENT, _KEY)
        with pytest.raises(DuplicateRequestError) as exc:
            store.begin(_CLIENT, _KEY)
        assert exc.value.state is IdempotencyState.IN_FLIGHT

    def test_a_completed_key_is_a_duplicate_too(self) -> None:
        store = InMemoryIdempotencyStore(_TTL)
        store.begin(_CLIENT, _KEY)
        store.complete(_CLIENT, _KEY, make_usage())
        with pytest.raises(DuplicateRequestError) as exc:
            store.begin(_CLIENT, _KEY)
        assert exc.value.state is IdempotencyState.COMPLETED

    def test_keys_of_different_clients_never_collide(self) -> None:
        store = InMemoryIdempotencyStore(_TTL)
        store.begin(_CLIENT, _KEY)
        store.begin(ClientId("cli-2"), _KEY)

    def test_parallel_claims_let_exactly_one_through(self) -> None:
        store = InMemoryIdempotencyStore(_TTL)
        start = threading.Barrier(16)
        outcomes: list[str] = []

        def claim() -> None:
            start.wait()
            try:
                store.begin(_CLIENT, _KEY)
                outcomes.append("claimed")
            except DuplicateRequestError:
                outcomes.append("duplicate")

        threads = [threading.Thread(target=claim) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(outcomes) == ["claimed"] + ["duplicate"] * 15


class TestReleasing:
    def test_a_released_key_can_be_claimed_again(self) -> None:
        store = InMemoryIdempotencyStore(_TTL)
        store.begin(_CLIENT, _KEY)
        store.release(_CLIENT, _KEY)
        store.begin(_CLIENT, _KEY)

    def test_a_completed_key_is_never_released(self) -> None:
        store = InMemoryIdempotencyStore(_TTL)
        store.begin(_CLIENT, _KEY)
        store.complete(_CLIENT, _KEY, make_usage())
        store.release(_CLIENT, _KEY)
        with pytest.raises(DuplicateRequestError):
            store.begin(_CLIENT, _KEY)

    def test_an_unknown_key_is_ignored(self) -> None:
        store = InMemoryIdempotencyStore(_TTL)
        store.release(_CLIENT, _KEY)
        store.complete(_CLIENT, _KEY, make_usage())


class TestExpiry:
    def test_an_expired_key_can_be_claimed_again(self) -> None:
        store = InMemoryIdempotencyStore(_EXPIRED)
        store.begin(_CLIENT, _KEY)
        store.begin(_CLIENT, _KEY)

    def test_completing_an_expired_key_is_ignored(self) -> None:
        store = InMemoryIdempotencyStore(_EXPIRED)
        store.begin(_CLIENT, _KEY)
        store.complete(_CLIENT, _KEY, make_usage())
        store.begin(_CLIENT, _KEY)

    def test_completing_twice_is_ignored(self) -> None:
        store = InMemoryIdempotencyStore(_TTL)
        store.begin(_CLIENT, _KEY)
        store.complete(_CLIENT, _KEY, make_usage())
        store.complete(_CLIENT, _KEY, make_usage())
