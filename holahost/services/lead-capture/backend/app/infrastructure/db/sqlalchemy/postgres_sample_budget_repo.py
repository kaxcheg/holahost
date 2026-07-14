from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import RowMapping, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from domain.entities.sample_budget_state import SampleBudgetState
from infrastructure.db.sqlalchemy import schema
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork


def _to_values(state: SampleBudgetState) -> dict[str, Any]:
    # Column 'date' bridges to the entity attribute 'day' here — the misalignment lives in the mapper.
    return {
        "date": state.day,
        "output_tokens_used": state.output_tokens_used,
        "dollars_spent_est": state.dollars_spent_est,
    }


def _from_row(row: RowMapping) -> SampleBudgetState:
    return SampleBudgetState.from_repo(
        day=row["date"],
        output_tokens_used=int(row["output_tokens_used"]),
        dollars_spent_est=float(row["dollars_spent_est"]),  # NUMERIC -> Decimal -> float (C-07)
    )


class PostgresSampleBudgetRepo:
    """Postgres adapter for the ``SampleBudgetRepo`` port (spec §4.5); runs on ``uow.connection``."""

    def __init__(self, uow: PostgresUnitOfWork) -> None:
        self._uow = uow

    def get_or_create(self, day: date) -> SampleBudgetState:
        self._ensure_row(day)
        return _from_row(self._require(self._select(day, lock=False)))

    def get_or_create_for_update(self, day: date) -> SampleBudgetState:
        self._ensure_row(day)
        return _from_row(self._require(self._select(day, lock=True)))

    def save(self, state: SampleBudgetState) -> None:
        values = _to_values(state)
        del values["date"]  # PK is the WHERE key, not a SET target
        self._uow.connection.execute(
            update(schema.sample_budget)
            .where(schema.sample_budget.c.date == state.day)
            .values(values)
        )

    def _ensure_row(self, day: date) -> None:
        self._uow.connection.execute(
            pg_insert(schema.sample_budget)
            .values(date=day)
            .on_conflict_do_nothing(index_elements=["date"])
        )

    def _select(self, day: date, *, lock: bool) -> RowMapping | None:
        stmt = select(schema.sample_budget).where(schema.sample_budget.c.date == day)
        if lock:
            stmt = stmt.with_for_update()
        return self._uow.connection.execute(stmt).mappings().one_or_none()  # lookup by PK date

    @staticmethod
    def _require(row: RowMapping | None) -> RowMapping:
        if row is None:  # unreachable: ON CONFLICT DO NOTHING guarantees the row exists
            raise RuntimeError("sample_budget row missing after upsert")
        return row


if TYPE_CHECKING:
    from application.ports.repos import SampleBudgetRepo

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: PostgresSampleBudgetRepo) -> SampleBudgetRepo:
        return x
