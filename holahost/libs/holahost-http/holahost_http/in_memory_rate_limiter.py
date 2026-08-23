"""Process-local implementation of the ``RateLimiter`` port."""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from holahost_http.errors import RateLimitExceededError

_Key = tuple[str, str, str]  # (client_id, subject, bucket)

DEFAULT_MAX_TRACKED_KEYS = 100_000


class InMemoryRateLimiter:
    """In-process counters, fixed windows, bounded memory.

    Counters live in this process only and reset when it restarts. With more than one
    replica each keeps its own tally, so the effective ceiling multiplies by the
    replica count — the limiter is a guard against a runaway caller, not an accounting
    system. Moving to a shared store is a different implementation of the same port.

    Windows are epoch-floor-aligned (``epoch - epoch % window_seconds``) so every key
    resets on the same wall-clock boundaries.

    **Bounded on purpose.** The key is derived from caller identity, so an unbounded
    map grows with the number of distinct callers ever seen and never shrinks:
    expiring a window rewrites that key's counter, it does not remove the key, and the
    keys that would need removing are exactly the ones nobody is asking about any
    more. Sweeping on a timer would be a second mechanism guessing at the same fact.
    Instead the map is an LRU with a hard ceiling: the least recently consulted key is
    evicted when a new one arrives at capacity. Evicting a key forgives whatever it had
    counted, which is the right trade — the alternative is unbounded growth driven by
    whoever sends the most distinct identities, i.e. exactly the caller a limiter
    exists to contain. Size the ceiling above the plausible number of concurrently
    active callers and eviction stays a theoretical event for legitimate traffic.

    Args:
        cap_by_bucket: Ceiling per ``(bucket, is_service)`` pair — requests per window.
        window_seconds: Window length.
        max_tracked_keys: LRU ceiling on distinct callers tracked at once.
        clock: Injectable time source, for tests.
    """

    def __init__(
        self,
        cap_by_bucket: dict[tuple[str, bool], int],
        window_seconds: int,
        max_tracked_keys: int = DEFAULT_MAX_TRACKED_KEYS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_tracked_keys < 1:
            raise ValueError("max_tracked_keys must be at least 1")
        self._cap_by_bucket = cap_by_bucket
        self._window_seconds = window_seconds
        self._max_tracked_keys = max_tracked_keys
        self._clock = clock
        self._lock = threading.Lock()
        # key -> (window_start, count), in least-recently-used-first order.
        self._counters: OrderedDict[_Key, tuple[int, int]] = OrderedDict()

    def check(self, *, client_id: str, subject: str, bucket: str, is_service: bool) -> None:
        cap = self._cap_by_bucket[bucket, is_service]
        key: _Key = (client_id, subject, bucket)
        now = self._clock()
        window_start = int(now) - int(now) % self._window_seconds

        with self._lock:
            stored_window, count = self._counters.get(key, (window_start, 0))
            if stored_window != window_start:
                count = 0
            count += 1
            self._counters[key] = (window_start, count)
            self._counters.move_to_end(key)
            while len(self._counters) > self._max_tracked_keys:
                self._counters.popitem(last=False)

        if count > cap:
            window_end = window_start + self._window_seconds
            raise RateLimitExceededError(retry_after=max(1, math.ceil(window_end - now)))
