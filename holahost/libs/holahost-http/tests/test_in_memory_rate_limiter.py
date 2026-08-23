import pytest

from holahost_http.errors import RateLimitExceededError
from holahost_http.in_memory_rate_limiter import InMemoryRateLimiter

WINDOW = 60


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def build(
    cap: int = 2, max_tracked_keys: int = 1000, clock: FakeClock | None = None
) -> InMemoryRateLimiter:
    return InMemoryRateLimiter(
        cap_by_bucket={("read", False): cap, ("read", True): cap},
        window_seconds=WINDOW,
        max_tracked_keys=max_tracked_keys,
        clock=clock or FakeClock(),
    )


def check(limiter: InMemoryRateLimiter, subject: str = "u", client_id: str = "c") -> None:
    limiter.check(client_id=client_id, subject=subject, bucket="read", is_service=False)


def test_counts_up_to_the_ceiling_then_refuses() -> None:
    limiter = build(cap=2)
    check(limiter)
    check(limiter)
    with pytest.raises(RateLimitExceededError):
        check(limiter)


def test_counter_resets_at_the_window_boundary() -> None:
    clock = FakeClock()
    limiter = build(cap=1, clock=clock)
    check(limiter)
    with pytest.raises(RateLimitExceededError):
        check(limiter)
    clock.now += WINDOW
    check(limiter)


def test_retry_after_points_at_the_end_of_the_window() -> None:
    clock = FakeClock(now=1_000_000.0)
    limiter = build(cap=1, clock=clock)
    check(limiter)
    with pytest.raises(RateLimitExceededError) as excinfo:
        check(limiter)
    window_end = int(clock.now) - int(clock.now) % WINDOW + WINDOW
    assert excinfo.value.retry_after == pytest.approx(window_end - clock.now, abs=1)


def test_tracked_keys_stay_bounded() -> None:
    """The key is derived from caller identity, so an unbounded map grows with every
    distinct caller ever seen and never shrinks — expiring a window rewrites a key, it
    does not remove it."""
    limiter = build(cap=100, max_tracked_keys=10)
    for n in range(1000):
        check(limiter, subject=f"u{n}")
    assert len(limiter._counters) == 10


def test_eviction_takes_the_least_recently_consulted_key() -> None:
    limiter = build(cap=1, max_tracked_keys=2)
    check(limiter, subject="keeps-being-used")
    check(limiter, subject="idle")
    # Re-consulting the first key makes "idle" the least recent one...
    with pytest.raises(RateLimitExceededError):
        check(limiter, subject="keeps-being-used")
    check(limiter, subject="newcomer")  # ...so "idle" is what gets dropped.
    assert ("c", "idle", "read") not in limiter._counters
    assert ("c", "keeps-being-used", "read") in limiter._counters


def test_a_ceiling_of_zero_tracked_keys_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="max_tracked_keys"):
        build(max_tracked_keys=0)
