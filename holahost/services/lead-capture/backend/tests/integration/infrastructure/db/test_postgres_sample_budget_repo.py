from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from infrastructure.db.sqlalchemy.postgres_sample_budget_repo import PostgresSampleBudgetRepo
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork

_DAY = date(2026, 6, 20)


@pytest.mark.integration
def test_get_or_create_initializes_zeroed(uow: PostgresUnitOfWork) -> None:
    with uow.transaction():
        state = PostgresSampleBudgetRepo(uow).get_or_create(_DAY)
    assert state.day == _DAY
    assert state.output_tokens_used == 0
    assert isinstance(state.dollars_spent_est, float)
    assert state.dollars_spent_est == 0.0


@pytest.mark.integration
def test_get_or_create_is_idempotent(uow: PostgresUnitOfWork) -> None:
    repo = PostgresSampleBudgetRepo(uow)
    with uow.transaction():
        repo.get_or_create(_DAY)
        repo.get_or_create(_DAY)  # no duplicate-key error
        rows = uow.connection.execute(
            text("SELECT count(*) FROM sample_budget WHERE date = :day"), {"day": _DAY}
        ).fetchone()
    assert rows is not None
    assert rows[0] == 1


@pytest.mark.integration
def test_save_persists_usage(uow: PostgresUnitOfWork) -> None:
    repo = PostgresSampleBudgetRepo(uow)
    with uow.transaction():
        state = repo.get_or_create_for_update(_DAY)
        state.add_usage(output_tokens=500, dollars=1.25)
        repo.save(state)
    with uow.transaction():
        reloaded = repo.get_or_create(_DAY)
    assert reloaded.output_tokens_used == 500
    assert reloaded.dollars_spent_est == pytest.approx(1.25)
