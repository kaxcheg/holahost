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

        Race-protection contract (adapter requirement — separate from atomicity, which the use case
        already gets from ``uow.transaction()``): concurrent ``check_and_increment`` calls for the
        same ``(scope, subject, current window)`` MUST NOT both pass the cap. The adapter must
        serialize the read-and-increment against concurrent callers — e.g. a conditional
        increment-and-return (``UPDATE ... SET count = count + 1 ... RETURNING count``, cap-checked
        on the returned value; or a guarded ``WHERE count < cap`` treating zero rows updated as
        "exceeded") or a row lock. Under READ COMMITTED a plain SELECT-then-UPDATE does NOT prevent
        the race: two concurrent calls both read ``count = N`` and both pass, overshooting the cap.
        The transaction boundary cannot prevent this interleaving — only the adapter can
        (spec §8.2.8 / §9.0).

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
