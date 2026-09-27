"""The first migration builds what the schema declares, and the database keeps its invariants."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from holahost_db import IntegrityError, SqlAlchemyUnitOfWork, translate_db_errors
from sqlalchemy import insert
from tests._support.db import superuser_env

from infrastructure.db.schema import usage_records

pytestmark = pytest.mark.integration

_ALEMBIC_INI = Path(__file__).resolve().parents[4] / "alembic.ini"


def _row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": uuid.uuid4(),
        "request_id": "req-1",
        "client_id": "cli-1",
        "subject": "cli-1",
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "input_tokens": 10,
        "output_tokens": 5,
        "latency_ms": 900,
        "downgraded": False,
        "failed_over": False,
        "created_at": datetime.now(tz=UTC),
    }
    return {**row, **changes}


class TestTheMigration:
    def test_the_database_matches_the_schema(self, superuser_dsn: str) -> None:
        # `alembic check` raises on any operation autogenerate would still render — a column, an
        # index or a type the migration and `schema.py` disagree about.
        with pytest.MonkeyPatch.context() as mp:
            superuser_env(mp, superuser_dsn)
            command.check(Config(str(_ALEMBIC_INI)))


class TestTheDatabasesInvariants:
    @pytest.mark.parametrize(
        "changes", [{"input_tokens": -1}, {"output_tokens": -1}, {"latency_ms": -1}]
    )
    def test_a_negative_figure_is_refused(
        self, uow: SqlAlchemyUnitOfWork, changes: dict[str, object]
    ) -> None:
        with pytest.raises(IntegrityError), uow, translate_db_errors():
            uow.connection().execute(insert(usage_records).values(_row(**changes)))
