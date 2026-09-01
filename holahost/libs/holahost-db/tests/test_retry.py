from __future__ import annotations

import pytest

from holahost_db import ConcurrentUpdateError, StorageUnavailableError, retry_on_concurrent_update


class TestRetryOnConcurrentUpdate:
    def test_a_first_attempt_that_succeeds_is_not_repeated(self) -> None:
        attempts = 0

        def once() -> str:
            nonlocal attempts
            attempts += 1
            return "done"

        assert retry_on_concurrent_update(once) == "done"
        assert attempts == 1

    def test_it_retries_until_one_succeeds(self) -> None:
        attempts = 0

        def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConcurrentUpdateError
            return "done"

        assert retry_on_concurrent_update(flaky) == "done"
        assert attempts == 3

    def test_it_gives_up_after_the_declared_number_of_retries(self) -> None:
        attempts = 0

        def always_conflicts() -> None:
            nonlocal attempts
            attempts += 1
            raise ConcurrentUpdateError

        with pytest.raises(ConcurrentUpdateError):
            retry_on_concurrent_update(always_conflicts, max_retries=2)

        # Initial attempt plus two retries. A caller that keeps losing is contending with
        # something that will not clear inside one request.
        assert attempts == 3

    def test_only_a_concurrency_conflict_is_retried(self) -> None:
        # An unreachable database is not going to become reachable by trying again inside
        # the same request, and a defect must not be repeated at all.
        attempts = 0

        def unavailable() -> None:
            nonlocal attempts
            attempts += 1
            raise StorageUnavailableError

        with pytest.raises(StorageUnavailableError):
            retry_on_concurrent_update(unavailable)

        assert attempts == 1
