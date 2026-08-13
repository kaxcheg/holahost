from __future__ import annotations

import pytest

from application.ports.rate import RateLimitExceededError
from infrastructure.rate.in_memory_rate_limiter import InMemoryRateLimiter


class TestInMemoryRateLimiter:
    def test_allows_requests_under_the_cap(self) -> None:
        limiter = InMemoryRateLimiter(
            cap_by_bucket={"read": 3}, window_seconds=3600, clock=lambda: 0.0
        )
        for _ in range(3):
            limiter.check("client-1", "sub-1", "read")  # must not raise

    def test_rejects_the_request_over_the_cap(self) -> None:
        limiter = InMemoryRateLimiter(
            cap_by_bucket={"read": 2}, window_seconds=3600, clock=lambda: 0.0
        )
        limiter.check("client-1", "sub-1", "read")
        limiter.check("client-1", "sub-1", "read")
        with pytest.raises(RateLimitExceededError) as exc:
            limiter.check("client-1", "sub-1", "read")
        assert exc.value.retry_after > 0

    def test_buckets_are_independent(self) -> None:
        limiter = InMemoryRateLimiter(
            cap_by_bucket={"read": 1, "ingest": 1}, window_seconds=3600, clock=lambda: 0.0
        )
        limiter.check("client-1", "sub-1", "read")
        limiter.check("client-1", "sub-1", "ingest")  # different bucket, must not raise

    def test_keys_are_independent_per_client_and_subject(self) -> None:
        limiter = InMemoryRateLimiter(
            cap_by_bucket={"read": 1}, window_seconds=3600, clock=lambda: 0.0
        )
        limiter.check("client-1", "sub-1", "read")
        limiter.check("client-1", "sub-2", "read")  # different subject, must not raise
        limiter.check("client-2", "sub-1", "read")  # different client, must not raise

    def test_window_reset_allows_requests_again(self) -> None:
        now = {"t": 0.0}
        limiter = InMemoryRateLimiter(
            cap_by_bucket={"read": 1}, window_seconds=60, clock=lambda: now["t"]
        )
        limiter.check("client-1", "sub-1", "read")
        with pytest.raises(RateLimitExceededError):
            limiter.check("client-1", "sub-1", "read")
        now["t"] = 61.0  # next epoch-floor window
        limiter.check("client-1", "sub-1", "read")  # must not raise

    def test_retry_after_is_seconds_remaining_in_window(self) -> None:
        now = {"t": 10.0}
        limiter = InMemoryRateLimiter(
            cap_by_bucket={"read": 1}, window_seconds=60, clock=lambda: now["t"]
        )
        limiter.check("client-1", "sub-1", "read")  # window_start = 0, window_end = 60
        with pytest.raises(RateLimitExceededError) as exc:
            limiter.check("client-1", "sub-1", "read")
        assert exc.value.retry_after == 50
