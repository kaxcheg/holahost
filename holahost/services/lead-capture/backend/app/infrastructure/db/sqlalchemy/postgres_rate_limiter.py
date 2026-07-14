from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.exceptions import RateLimitExceededError
from application.ports.rate import RateLimitScope
from config.config import Settings
from infrastructure.db.sqlalchemy import schema
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork


class PostgresRateLimiter:
    """Fixed-window rate limiter (spec §4.4, §8.2.8); runs on ``uow.connection``.

    One atomic ``INSERT … ON CONFLICT DO UPDATE … RETURNING counter`` per call — the race-protection
    the ``RateLimiter`` port mandates (a plain SELECT-then-UPDATE under READ COMMITTED would let two
    callers both pass the cap). A rejected increment rolls back with the enclosing
    ``uow.transaction()`` so the counter pins at the cap.
    """

    def __init__(self, uow: PostgresUnitOfWork, settings: Settings) -> None:
        self._uow = uow
        self._cap_by_scope = {
            RateLimitScope.IP: settings.rate_limit_per_ip,
            RateLimitScope.MAGIC_LINK: settings.rate_limit_per_magic_link,
        }
        self._window_seconds = settings.rate_limit_window_seconds

    def check_and_increment(self, scope: RateLimitScope, subject: str) -> None:
        now = datetime.now(tz=UTC)
        window_start = self._window_start(now)
        stmt = (
            pg_insert(schema.rate_limit_counters)
            .values(scope=scope.value, subject=subject, window_start=window_start, counter=1)
            .on_conflict_do_update(
                index_elements=["scope", "subject", "window_start"],
                set_={"counter": schema.rate_limit_counters.c.counter + 1},
            )
            .returning(schema.rate_limit_counters.c.counter)
        )
        counter = self._uow.connection.execute(stmt).scalar_one()
        if counter > self._cap_by_scope[scope]:
            window_end = window_start + timedelta(seconds=self._window_seconds)
            retry_after = max(1, math.ceil((window_end - now).total_seconds()))
            raise RateLimitExceededError(scope=scope.value, retry_after_seconds=retry_after)

    def cleanup_old_windows(self, threshold: datetime) -> int:
        result = self._uow.connection.execute(
            delete(schema.rate_limit_counters).where(
                schema.rate_limit_counters.c.window_start < threshold
            )
        )
        return result.rowcount

    def _window_start(self, now: datetime) -> datetime:
        # Epoch-floor to the window size (from config), NOT a hardcoded top-of-hour (advisor #1).
        # Time since Unix epoch (1970-01-01T00:00:00Z) is partitioned
        # into fixed-size windows of self._window_seconds.
        # epoch - (epoch % self._window_seconds) gives the start of the current window.
        epoch = int(now.timestamp())
        return datetime.fromtimestamp(epoch - (epoch % self._window_seconds), tz=UTC)


if TYPE_CHECKING:
    from application.ports.rate import RateLimiter

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: PostgresRateLimiter) -> RateLimiter:
        return x
