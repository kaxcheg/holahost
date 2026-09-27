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
from tests._support.db import build_test_uow, superuser_env

from scripts.provision_app_role import provision

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"

# A dedicated, unprivileged role for integration tests. testcontainers' default connection
# is a Postgres superuser, which may do anything: tests run as the role the deploy creates,
# holding only its grants, so a statement needing more fails here rather than in prod. The
# role is created by the very same code the deploy runs (`scripts/provision_app_role.py`), so
# what these tests exercise is the real provisioning, not a test-local imitation that could
# drift from it.
_APP_ROLE = "llm_client_app"
_APP_ROLE_PASSWORD = "llm-client-app-test-only"  # test-only, not a real secret


def _run_migrations(dsn: str) -> None:
    """`pytest.MonkeyPatch.context()`, not a session-scoped fixture: those undo only at the
    end of the run, and a bare `pytest` collects `tests/integration/` before `tests/unit/`,
    so the container's random port leaks into unit tests that assert the fixed
    `postgres:5432`. These variables are needed for the `command.upgrade(...)` below alone.
    """
    with pytest.MonkeyPatch.context() as mp:
        superuser_env(mp, dsn)
        command.upgrade(Config(str(_ALEMBIC_INI)), "head")


def _provision_app_role(superuser_dsn: str) -> None:
    """Create the unprivileged app role by running the deploy's own provisioning script.

    Same scoping reasoning as `_run_migrations` above for the `MonkeyPatch.context()`.
    """
    with pytest.MonkeyPatch.context() as mp:
        superuser_env(mp, superuser_dsn)
        mp.setenv("POSTGRES_USER", _APP_ROLE)
        mp.setenv("POSTGRES_PASSWORD", _APP_ROLE_PASSWORD)
        provision()
    # TRUNCATE is for `_truncate_after` below, not something the application does — `provision()`
    # deliberately does not grant it, so the privileges the deploy hands the app role stay honest.
    engine = create_engine(superuser_dsn)
    with engine.connect() as connection:
        connection.execute(text(f"GRANT TRUNCATE ON usage_records TO {_APP_ROLE}"))
        connection.commit()
    engine.dispose()


def _as_app_role(superuser_dsn: str) -> str:
    parsed = urlsplit(superuser_dsn)
    netloc = f"{_APP_ROLE}:{_APP_ROLE_PASSWORD}@{parsed.hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


@pytest.fixture(scope="session")
def _dsns() -> Iterator[tuple[str, str]]:
    with PostgresContainer("postgres:16") as pg:
        # driver="psycopg" so the fixture hands out the same shape `config.settings` builds —
        # 'postgresql+psycopg://...', dialect included — and nothing downstream rewrites it.
        superuser_dsn = pg.get_connection_url(driver="psycopg")
        _run_migrations(superuser_dsn)
        _provision_app_role(superuser_dsn)
        yield superuser_dsn, _as_app_role(superuser_dsn)


@pytest.fixture(scope="session")
def pg_dsn(_dsns: tuple[str, str]) -> str:
    return _dsns[1]


@pytest.fixture(scope="session")
def superuser_dsn(_dsns: tuple[str, str]) -> str:
    """Only for what the deploy runs elevated — migrations and checks on them. Every other test
    uses `pg_dsn`/`uow`, the unprivileged role the application runs as."""
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
        uow.connection().execute(text("TRUNCATE TABLE usage_records"))
