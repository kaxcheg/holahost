from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer
from tests._support.db import build_test_uow

from infrastructure.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"

# A dedicated, unprivileged role for integration tests. testcontainers' default
# connection is a Postgres superuser, and a superuser bypasses row-level security
# unconditionally — no policy, no FORCE ROW LEVEL SECURITY, can change that (§8.0).
# Tests must run as a non-superuser role or RLS enforcement is never actually
# exercised, only assumed.
_APP_ROLE = "rag_documents_app"
_APP_ROLE_PASSWORD = "rag-documents-app-test-only"  # test-only, not a real secret


def _run_migrations(dsn: str) -> None:
    os.environ["DATABASE_URL"] = dsn  # env.py reads DATABASE_URL
    command.upgrade(Config(str(_ALEMBIC_INI)), "head")


def _create_app_role(superuser_dsn: str) -> None:
    engine = create_engine(superuser_dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.connect() as conn:
        conn.execute(text(f"CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{_APP_ROLE_PASSWORD}'"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO " + _APP_ROLE))
        conn.execute(
            # TRUNCATE is for the _truncate_after test-isolation fixture below, not
            # something the application itself does — it bypasses RLS entirely
            # (whole-table, not row-filtered), which is exactly what test cleanup wants.
            text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE "
                f"ON documents, chunks TO {_APP_ROLE}"
            )
        )
        conn.commit()
    engine.dispose()


def _as_app_role(superuser_dsn: str) -> str:
    parsed = urlsplit(superuser_dsn)
    netloc = f"{_APP_ROLE}:{_APP_ROLE_PASSWORD}@{parsed.hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


@pytest.fixture(scope="session")
def _dsns() -> Iterator[tuple[str, str]]:
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        superuser_dsn = pg.get_connection_url(driver=None)  # plain 'postgresql://...'
        _run_migrations(superuser_dsn)
        _create_app_role(superuser_dsn)
        yield superuser_dsn, _as_app_role(superuser_dsn)


@pytest.fixture(scope="session")
def pg_dsn(_dsns: tuple[str, str]) -> str:
    return _dsns[1]


@pytest.fixture(scope="session")
def superuser_dsn(_dsns: tuple[str, str]) -> str:
    """Only for the one test proving a superuser bypasses RLS unconditionally
    (test_migration_applies.py) — every other test must use `pg_dsn`/`uow`, which
    are the unprivileged role RLS is actually meant to restrict."""
    return _dsns[0]


@pytest.fixture(scope="session")
def uow(pg_dsn: str) -> Iterator[SqlAlchemyUnitOfWork]:
    unit = build_test_uow(pg_dsn)
    try:
        yield unit
    finally:
        unit.dispose()


@pytest.fixture(autouse=True)
def _truncate_after(uow: SqlAlchemyUnitOfWork) -> Iterator[None]:
    yield
    with uow:
        assert uow.active_connection is not None
        uow.active_connection.execute(text("TRUNCATE TABLE documents, chunks CASCADE"))
