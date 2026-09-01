from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from alembic import command
from alembic.config import Config
from holahost_db import SqlAlchemyUnitOfWork
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer
from tests._support.db import build_test_uow

from scripts.provision_app_role import provision

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"

# A dedicated, unprivileged role for integration tests. testcontainers' default
# connection is a Postgres superuser, and a superuser bypasses row-level security
# unconditionally — no policy, no FORCE ROW LEVEL SECURITY, can change that (§8.0).
# Tests must run as a non-superuser role or RLS enforcement is never actually
# exercised, only assumed. The role is created by the very same code the deploy runs
# (`scripts/provision_app_role.py`), so what these tests exercise is the real
# provisioning, not a test-local imitation of it that could drift from it.
_APP_ROLE = "rag_documents_app"
_APP_ROLE_PASSWORD = "rag-documents-app-test-only"  # test-only, not a real secret


def _superuser_env(mp: pytest.MonkeyPatch, dsn: str) -> None:
    """Point the standalone entry points below at this testcontainers instance.

    `POSTGRES_SUPERUSER`/`POSTGRES_SUPERUSER_PASSWORD`, not `POSTGRES_USER`/`POSTGRES_PASSWORD`:
    both `migrations/env.py` and `scripts/provision_app_role.py` are elevated operations and read
    the superuser pair (see their own docstrings) — the plain pair means the app's own,
    unprivileged identity everywhere in this service, and testcontainers' default connection is
    the superuser.
    """
    parts = urlsplit(dsn)
    assert parts.username and parts.password and parts.hostname and parts.port
    mp.setenv("POSTGRES_SUPERUSER", parts.username)
    mp.setenv("POSTGRES_SUPERUSER_PASSWORD", parts.password)
    mp.setenv("POSTGRES_DB", parts.path.lstrip("/"))
    mp.setenv("POSTGRES_HOST", parts.hostname)
    mp.setenv("POSTGRES_PORT", str(parts.port))


def _run_migrations(dsn: str) -> None:
    """`pytest.MonkeyPatch.context()`, not a session-scoped fixture: those undo only at the
    end of the run, and a bare `pytest` collects `tests/integration/` before `tests/unit/`,
    so the container's random port leaks into `tests/unit/config/test_settings.py`, which
    asserts the fixed `postgres:5432`. These variables are needed for the single
    `command.upgrade(...)` below and nothing after it.
    """
    with pytest.MonkeyPatch.context() as mp:
        _superuser_env(mp, dsn)
        command.upgrade(Config(str(_ALEMBIC_INI)), "head")


def _provision_app_role(superuser_dsn: str) -> None:
    """Create the unprivileged app role by running the deploy's own provisioning script.

    Same scoping reasoning as `_run_migrations` above for the `MonkeyPatch.context()`.
    """
    with pytest.MonkeyPatch.context() as mp:
        _superuser_env(mp, superuser_dsn)
        mp.setenv("POSTGRES_USER", _APP_ROLE)
        mp.setenv("POSTGRES_PASSWORD", _APP_ROLE_PASSWORD)
        provision()

    # TRUNCATE is for the _truncate_after test-isolation fixture below, not something the
    # application itself does — it bypasses RLS entirely (whole-table, not row-filtered), which
    # is exactly what test cleanup wants and exactly why `provision()` does not grant it. Granted
    # here, separately, so the privileges the deploy actually hands the app role stay honest.
    engine = create_engine(superuser_dsn)
    with engine.connect() as conn:
        conn.execute(text(f"GRANT TRUNCATE ON documents, chunks TO {_APP_ROLE}"))
        conn.commit()
    engine.dispose()


def _as_app_role(superuser_dsn: str) -> str:
    parsed = urlsplit(superuser_dsn)
    netloc = f"{_APP_ROLE}:{_APP_ROLE_PASSWORD}@{parsed.hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


@pytest.fixture(scope="session")
def _dsns() -> Iterator[tuple[str, str]]:
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        # driver="psycopg" so the fixture hands out the same shape `config.settings` builds —
        # 'postgresql+psycopg://...', dialect included — and nothing downstream has to rewrite it.
        superuser_dsn = pg.get_connection_url(driver="psycopg")
        _run_migrations(superuser_dsn)
        _provision_app_role(superuser_dsn)
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
