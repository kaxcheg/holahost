from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from application.exceptions import RateLimitExceededError
from application.ports.rate import RateLimitScope
from infrastructure.db.sqlalchemy.postgres_rate_limiter import PostgresRateLimiter
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork
from tests._support.settings import make_settings


@pytest.mark.integration
def test_allows_up_to_cap_then_raises(uow: PostgresUnitOfWork) -> None:
    settings = make_settings(rate_limit_per_ip=3, rate_limit_window_seconds=3600)
    limiter = PostgresRateLimiter(uow, settings)
    with uow.transaction():
        for _ in range(3):
            limiter.check_and_increment(RateLimitScope.IP, "1.2.3.4")
    # pytest.raises is the OUTER cm so uow.transaction() exits first → the rejected increment rolls
    # back (counter pins at the cap), then pytest.raises catches the error.
    with pytest.raises(RateLimitExceededError) as exc, uow.transaction():
        limiter.check_and_increment(RateLimitScope.IP, "1.2.3.4")
    assert exc.value.scope == "ip"
    assert 0 < exc.value.retry_after_seconds <= 3600


@pytest.mark.integration
def test_distinct_subjects_and_scopes_independent(uow: PostgresUnitOfWork) -> None:
    settings = make_settings(rate_limit_per_ip=1, rate_limit_per_magic_link=1)
    limiter = PostgresRateLimiter(uow, settings)
    with uow.transaction():  # different subject + different scope → no interference
        limiter.check_and_increment(RateLimitScope.IP, "ip-a")
        limiter.check_and_increment(RateLimitScope.IP, "ip-b")
        limiter.check_and_increment(RateLimitScope.MAGIC_LINK, "ip-a")


@pytest.mark.integration
def test_cleanup_old_windows_deletes_only_stale(uow: PostgresUnitOfWork) -> None:
    settings = make_settings(rate_limit_per_ip=100)
    limiter = PostgresRateLimiter(uow, settings)
    with uow.transaction():
        limiter.check_and_increment(RateLimitScope.IP, "x")  # current window row
        old = datetime.now(tz=UTC) - timedelta(days=2)
        uow.connection.execute(
            text(
                "INSERT INTO rate_limit_counters (scope, subject, window_start, counter) "
                "VALUES ('ip', 'old', :ws, 5)"
            ),
            {"ws": old},
        )
    with uow.transaction():
        deleted = limiter.cleanup_old_windows(datetime.now(tz=UTC) - timedelta(days=1))
    assert deleted == 1
    with uow.transaction():
        remaining = uow.connection.execute(
            text("SELECT count(*) FROM rate_limit_counters")
        ).fetchone()
    assert remaining is not None
    assert remaining[0] == 1
