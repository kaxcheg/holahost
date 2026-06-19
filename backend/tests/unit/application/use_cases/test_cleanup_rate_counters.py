from __future__ import annotations

from datetime import UTC, datetime, timedelta

from application.use_cases.cleanup_rate_counters import CleanupRateCountersUseCase
from tests._support.fakes import FakeRateLimiter, FakeUnitOfWork
from tests._support.settings import make_settings


class TestCleanupRateCounters:
    def test_returns_deleted_count_and_commits(self) -> None:
        rate = FakeRateLimiter(cleanup_deleted=7)
        uow = FakeUnitOfWork()
        uc = CleanupRateCountersUseCase(rate=rate, uow=uow, settings=make_settings())
        result = uc.execute()
        assert result.deleted_windows == 7
        assert uow.commits == 1
        assert uow.rollbacks == 0

    def test_threshold_is_now_minus_window(self) -> None:
        rate = FakeRateLimiter()
        uc = CleanupRateCountersUseCase(
            rate=rate,
            uow=FakeUnitOfWork(),
            settings=make_settings(max_rate_limit_window_seconds=3600),
        )
        before = datetime.now(tz=UTC)
        uc.execute()
        after = datetime.now(tz=UTC)
        (threshold,) = rate.cleanup_calls
        assert before - timedelta(hours=1) <= threshold <= after - timedelta(hours=1)
