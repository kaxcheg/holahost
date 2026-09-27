"""`BudgetRepo` over Postgres: a budget is an aggregate over the usage log for the current
window."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from holahost_db import SqlAlchemyUnitOfWork, translate_db_errors
from sqlalchemy import ColumnElement, and_, func, not_, select

from domain.entities.budget import Budget
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from domain.value_objects.provider_name import ProviderName
from domain.value_objects.token_count import TokenCount
from domain.value_objects.usage import Usage
from infrastructure.db.schema import usage_records


def current_window_start(now: datetime | None = None) -> datetime:
    """Midnight UTC of the day `now` falls on — the present, by default.

    Computed here and bound into the query rather than left to the database's `now()`: the query
    and `Budget.window_start`, and the `Retry-After` derived from it, then agree by construction,
    whatever time zone the session runs in.
    """
    moment = (now if now is not None else datetime.now(tz=UTC)).astimezone(UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


class SqlAlchemyBudgetRepo:
    """Sums the usage log over the current window, against the ceilings the composition root
    hands in.

    No lock, by the port's contract: one aggregate is one statement, and overspend within a single
    call is accepted.
    """

    def __init__(self, uow: SqlAlchemyUnitOfWork, caps: Mapping[BudgetScope, Usage]) -> None:
        self._uow = uow
        self._caps = caps

    def client_state(
        self,
        scope: Literal[BudgetScope.CLIENT, BudgetScope.CLIENT_DOWNGRADE],
        client_id: ClientId,
    ) -> Budget:
        downgraded = usage_records.c.downgraded
        pool = downgraded if scope is BudgetScope.CLIENT_DOWNGRADE else not_(downgraded)
        return self._budget(
            scope, client_id, and_(usage_records.c.client_id == client_id.value, pool)
        )

    def provider_state(self, provider: ProviderName) -> Budget:
        return self._budget(
            BudgetScope.PROVIDER, provider, usage_records.c.provider == provider.value
        )

    def _budget(
        self, scope: BudgetScope, key: ClientId | ProviderName, subject: ColumnElement[bool]
    ) -> Budget:
        window_start = current_window_start()
        statement = select(
            func.coalesce(func.sum(usage_records.c.input_tokens), 0),
            func.coalesce(func.sum(usage_records.c.output_tokens), 0),
        ).where(subject, usage_records.c.created_at >= window_start)
        with translate_db_errors():
            spent_input, spent_output = self._uow.connection().execute(statement).one()
        return Budget(
            scope=scope,
            key=key,
            window_start=window_start,
            spent=Usage(
                input_tokens=TokenCount(int(spent_input)),
                output_tokens=TokenCount(int(spent_output)),
            ),
            caps=self._caps[scope],
        )
