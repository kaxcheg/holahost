from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"
# Truncated after every integration test (TRUNCATE isolation, C-04). CASCADE covers the FKs.
_TRUNCATE_SQL = (
    "TRUNCATE TABLE guidebooks, leads, chunks, sample_budget, rate_limit_counters CASCADE"
)


def _run_migrations(dsn: str) -> None:
    os.environ["DATABASE_URL"] = dsn  # env.py reads DATABASE_URL
    command.upgrade(Config(str(_ALEMBIC_INI)), "head")


@pytest.fixture(scope="session")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16") as pg:
        dsn = pg.get_connection_url(driver=None)  # plain 'postgresql://...' (raw psycopg + env.py)
        _run_migrations(dsn)
        yield dsn


@pytest.fixture(scope="session")
def uow(pg_dsn: str) -> Iterator[PostgresUnitOfWork]:
    unit = PostgresUnitOfWork(SecretStr(pg_dsn))
    try:
        yield unit
    finally:
        unit.close()


@pytest.fixture(autouse=True)
def _truncate_after(uow: PostgresUnitOfWork) -> Iterator[None]:
    yield
    with uow.transaction():
        uow.connection.execute(text(_TRUNCATE_SQL))
