from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CleanupResult:
    """Result of CleanupExpiredUseCase (spec §8.3 / §9.6).

    Args:
        expired_leads: Count of leads whose magic_link was expired.
        deleted_guidebooks: Count of guidebooks hard-deleted.
    """

    expired_leads: int
    deleted_guidebooks: int


@dataclass(frozen=True)
class RateCountersCleanupResult:
    """Result of CleanupRateCountersUseCase (spec §8.3 / §9.7).

    Args:
        deleted_windows: Count of rate-limit window rows deleted.
    """

    deleted_windows: int
