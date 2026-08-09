"""Tests for the retry-on-concurrent-update helper."""

from __future__ import annotations

import pytest

from application.ports.exceptions import ConcurrentUpdateError
from application.use_cases._retry import retry_on_concurrent_update


class TestRetryOnConcurrentUpdate:
    def test_returns_result_on_first_success(self) -> None:
        calls: list[int] = []

        def fn() -> str:
            calls.append(1)
            return "ok"

        assert retry_on_concurrent_update(fn) == "ok"
        assert len(calls) == 1

    def test_retries_and_succeeds_within_budget(self) -> None:
        calls: list[int] = []

        def fn() -> str:
            calls.append(1)
            if len(calls) < 3:
                raise ConcurrentUpdateError
            return "ok"

        assert retry_on_concurrent_update(fn) == "ok"
        assert len(calls) == 3

    def test_gives_up_after_max_retries_and_reraises(self) -> None:
        calls: list[int] = []

        def fn() -> str:
            calls.append(1)
            raise ConcurrentUpdateError

        with pytest.raises(ConcurrentUpdateError):
            retry_on_concurrent_update(fn)
        assert len(calls) == 3  # initial attempt + 2 retries, per §8.6
