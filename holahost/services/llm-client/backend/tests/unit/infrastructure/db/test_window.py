"""The budget window's boundary: midnight UTC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from infrastructure.db.sqlalchemy_budget_repo import current_window_start


class TestTheWindowStart:
    def test_is_midnight_utc_of_the_same_day(self) -> None:
        now = datetime(2026, 9, 27, 23, 59, 59, tzinfo=UTC)
        assert current_window_start(now) == datetime(2026, 9, 27, tzinfo=UTC)

    def test_a_moment_in_another_zone_is_read_in_utc(self) -> None:
        # 01:30 at UTC+3 is still 22:30 of the previous day in UTC.
        now = datetime(2026, 9, 28, 1, 30, tzinfo=timezone(timedelta(hours=3)))
        assert current_window_start(now) == datetime(2026, 9, 27, tzinfo=UTC)

    def test_defaults_to_the_present(self) -> None:
        start = current_window_start()
        assert start <= datetime.now(tz=UTC) < start + timedelta(days=1)
