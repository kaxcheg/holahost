from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from application.dto.cleanup import RateCountersCleanupResult
from application.ports.rate import RateLimiter
from application.ports.uow import UnitOfWork
from config.config import Settings


@dataclass
class CleanupRateCountersUseCase:
    """Delete stale fixed-window rate-limit rows (spec §9.7; cleanup-Lambda)."""

    rate: RateLimiter
    uow: UnitOfWork
    settings: Settings

    def execute(self) -> RateCountersCleanupResult:
        """Delete windows older than ``now - max_rate_limit_window``; return the deleted count.

        Returns:
            The number of deleted rate-counter rows (logged by the cleanup entry-point, §9.7).
        """
        threshold = datetime.now(tz=UTC) - self.settings.max_rate_limit_window
        with self.uow.transaction():
            deleted = self.rate.cleanup_old_windows(threshold)
        return RateCountersCleanupResult(deleted_windows=deleted)
