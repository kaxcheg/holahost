"""`SqlAlchemyBudgetRepo` against Postgres: the pools, the window, and exhaustion."""

from __future__ import annotations

from datetime import timedelta

import pytest
from holahost_db import SqlAlchemyUnitOfWork
from tests._support.builders import make_record, make_usage

from domain.entities.usage_record import UsageRecord
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from domain.value_objects.provider_name import ProviderName
from infrastructure.db.sqlalchemy_budget_repo import SqlAlchemyBudgetRepo, current_window_start
from infrastructure.db.sqlalchemy_usage_repo import SqlAlchemyUsageRepo

pytestmark = pytest.mark.integration

_CAPS = {
    BudgetScope.CLIENT: make_usage(1000, 100),
    BudgetScope.CLIENT_DOWNGRADE: make_usage(500, 50),
    BudgetScope.PROVIDER: make_usage(5000, 500),
}
_CLI_1 = ClientId("cli-1")


def _add(uow: SqlAlchemyUnitOfWork, *records: UsageRecord) -> None:
    with uow:
        repo = SqlAlchemyUsageRepo(uow)
        for record in records:
            repo.add(record)


def _repo(uow: SqlAlchemyUnitOfWork) -> SqlAlchemyBudgetRepo:
    return SqlAlchemyBudgetRepo(uow, _CAPS)


class TestAnEmptyLog:
    def test_nothing_is_spent_in_a_window_starting_at_midnight_utc(
        self, uow: SqlAlchemyUnitOfWork
    ) -> None:
        with uow:
            budget = _repo(uow).client_state(BudgetScope.CLIENT, _CLI_1)
        assert budget.spent == make_usage(0, 0)
        assert budget.caps == _CAPS[BudgetScope.CLIENT]
        assert budget.window_start == current_window_start()
        assert not budget.is_exhausted


class TestThePools:
    def _log(self, uow: SqlAlchemyUnitOfWork) -> None:
        _add(
            uow,
            make_record(client_id="cli-1", usage=make_usage(100, 10)),
            make_record(client_id="cli-1", usage=make_usage(20, 2)),
            make_record(client_id="cli-1", usage=make_usage(7, 1), downgraded=True),
            make_record(client_id="cli-2", usage=make_usage(900, 90)),
            make_record(client_id="cli-2", provider="other-vendor", usage=make_usage(3, 3)),
        )

    def test_the_client_pool_is_its_own_calls_that_were_not_downgraded(
        self, uow: SqlAlchemyUnitOfWork
    ) -> None:
        self._log(uow)
        with uow:
            budget = _repo(uow).client_state(BudgetScope.CLIENT, _CLI_1)
        assert budget.spent == make_usage(120, 12)

    def test_the_downgrade_pool_is_its_own_downgraded_calls(
        self, uow: SqlAlchemyUnitOfWork
    ) -> None:
        self._log(uow)
        with uow:
            budget = _repo(uow).client_state(BudgetScope.CLIENT_DOWNGRADE, _CLI_1)
        assert budget.spent == make_usage(7, 1)

    def test_a_provider_is_every_callers_calls_at_it(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._log(uow)
        with uow:
            budget = _repo(uow).provider_state(ProviderName("anthropic"))
        assert budget.spent == make_usage(1027, 103)
        assert budget.caps == _CAPS[BudgetScope.PROVIDER]


class TestTheWindow:
    def test_a_call_before_midnight_utc_is_not_counted(self, uow: SqlAlchemyUnitOfWork) -> None:
        _add(
            uow,
            make_record(
                usage=make_usage(100, 10),
                created_at=current_window_start() - timedelta(microseconds=1),
            ),
            make_record(usage=make_usage(5, 1)),
        )
        with uow:
            budget = _repo(uow).provider_state(ProviderName("anthropic"))
        assert budget.spent == make_usage(5, 1)


class TestExhaustion:
    def test_reaching_a_ceiling_exhausts_the_budget(self, uow: SqlAlchemyUnitOfWork) -> None:
        _add(uow, make_record(client_id="cli-1", usage=make_usage(1000, 0)))
        with uow:
            budget = _repo(uow).client_state(BudgetScope.CLIENT, _CLI_1)
        assert budget.is_exhausted
