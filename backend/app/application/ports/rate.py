from __future__ import annotations

from datetime import datetime
from enum import StrEnum, auto
from typing import Protocol


class RateLimitScope(StrEnum):
    """Rate-limit scope (spec §8.2.8).

    ``StrEnum`` + ``auto()`` yields lowercase member names ("ip" / "magic_link"), matching
    ``rate_limit_counters.scope`` (§4.4).
    """

    IP = auto()
    MAGIC_LINK = auto()


class RateLimiter(Protocol):
    """Port: fixed-window rate limiting + counter cleanup (spec §8.2.8)."""

    def check_and_increment(self, scope: RateLimitScope, subject: str) -> None:
        """Increment the current window's counter for ``(scope, subject)`` and enforce the cap.

        Args:
            scope: Whether the subject is an ip hash or a magic-link-derived id.
            subject: The counted subject (ip_hash, or str(lead.id) for MAGIC_LINK — §9.8).

        Raises:
            RateLimitExceededError: when the per-window cap is exceeded
                (application.exceptions, code ERR_RATE_LIMIT).
        """
        ...

    def cleanup_old_windows(self, threshold: datetime) -> int:
        """Delete rate-limit windows that ended before ``threshold``.

        Args:
            threshold: Cutoff; rows with ``window_start < threshold`` are removed.

        Returns:
            Number of deleted rows (logged by CleanupRateCountersUseCase, §9.7).
        """
        ...
