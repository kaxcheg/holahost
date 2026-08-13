from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

from application.ports.rate import RateLimitExceededError

_Key = tuple[str, str, str]  # (client_id, subject, bucket)


class InMemoryRateLimiter:
    """Adapter for the `RateLimiter` port — in-process counters, no persistence (ADR A-8:
    counters reset on restart by design; this service runs a single instance). Windows
    are epoch-floor-aligned (`epoch - epoch % window_seconds`) so every key resets at
    the same wall-clock boundaries. `check`-and-increment is guarded by a single
    `threading.Lock` — a dict read+write is nanoseconds, not worth per-key granularity
    (§8.0: not comparable in cost to forgoing a row lock in `top_k` — this is an
    in-process mutex around an integer increment, not a cross-transaction DB lock).
    """

    def __init__(
        self,
        cap_by_bucket: dict[str, int],
        window_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._cap_by_bucket = cap_by_bucket
        self._window_seconds = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._counters: dict[_Key, tuple[int, int]] = {}  # key -> (window_start, count)

    def check(self, client_id: str, subject: str, bucket: str) -> None:
        key: _Key = (client_id, subject, bucket)
        now = self._clock()
        window_start = int(now) - int(now) % self._window_seconds
        with self._lock:
            stored_window, count = self._counters.get(key, (window_start, 0))
            if stored_window != window_start:
                count = 0
            count += 1
            self._counters[key] = (window_start, count)
        if count > self._cap_by_bucket[bucket]:
            window_end = window_start + self._window_seconds
            retry_after = max(1, math.ceil(window_end - now))
            raise RateLimitExceededError(retry_after=retry_after)
