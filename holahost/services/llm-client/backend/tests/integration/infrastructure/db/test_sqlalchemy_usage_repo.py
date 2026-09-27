"""`SqlAlchemyUsageRepo` against Postgres: appending, and absorbing a re-insert."""

from __future__ import annotations

import pytest
from holahost_db import SqlAlchemyUnitOfWork
from sqlalchemy import RowMapping, select
from tests._support.builders import make_record, make_usage

from infrastructure.db.schema import usage_records
from infrastructure.db.sqlalchemy_usage_repo import SqlAlchemyUsageRepo

pytestmark = pytest.mark.integration


def _rows(uow: SqlAlchemyUnitOfWork) -> list[RowMapping]:
    with uow:
        return list(uow.connection().execute(select(usage_records)).mappings())


class TestAdd:
    def test_a_record_is_appended_with_every_field(self, uow: SqlAlchemyUnitOfWork) -> None:
        record = make_record(client_id="cli-1", usage=make_usage(120, 30), downgraded=True)

        with uow:
            SqlAlchemyUsageRepo(uow).add(record)

        [row] = _rows(uow)
        assert row["id"] == record.id
        assert (row["request_id"], row["client_id"], row["subject"]) == ("req-1", "cli-1", "cli-1")
        assert (row["provider"], row["model"]) == ("anthropic", "claude-haiku-4-5")
        assert (row["input_tokens"], row["output_tokens"], row["latency_ms"]) == (120, 30, 900)
        assert (row["downgraded"], row["failed_over"]) == (True, False)
        assert row["created_at"] == record.created_at

    def test_the_same_record_twice_is_one_row(self, uow: SqlAlchemyUnitOfWork) -> None:
        record = make_record()
        with uow:
            SqlAlchemyUsageRepo(uow).add(record)
        with uow:
            SqlAlchemyUsageRepo(uow).add(record)
        assert len(_rows(uow)) == 1
