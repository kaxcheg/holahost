"""Real (non-fake) database-adapter test helpers.

Builds an actual `SqlAlchemyUnitOfWork` against a raw DSN, for the integration fixtures and
for any test that exercises an adapter rather than a port double. Test-only: the
composition root shares one `Engine` per process and calls `SqlAlchemyUnitOfWork(engine)`
directly (`interface.http.dependencies.get_engine`/`get_uow`).

A service whose schema needs a per-connection codec builds its engine through its own
`infrastructure/db/engine.py` wrapper instead, so tests and the running process agree about
what a connection is.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from holahost_db import SqlAlchemyUnitOfWork, build_engine


def build_test_uow(database_url: str, *, pool_size: int = 5) -> SqlAlchemyUnitOfWork:
    """Build a UoW with its own freshly-built `Engine` from a raw DSN."""
    return SqlAlchemyUnitOfWork(build_engine(database_url, pool_size=pool_size))


def superuser_env(mp: pytest.MonkeyPatch, dsn: str) -> None:
    """Point the standalone elevated entry points at this testcontainers instance.

    `POSTGRES_SUPERUSER`/`POSTGRES_SUPERUSER_PASSWORD`, not `POSTGRES_USER`/`POSTGRES_PASSWORD`:
    both `migrations/env.py` and `scripts/provision_app_role.py` are elevated operations and
    read the superuser pair (see their own docstrings) — the plain pair means the app's own,
    unprivileged identity everywhere in this service, and testcontainers' default connection
    is the superuser.
    """
    parts = urlsplit(dsn)
    assert parts.username and parts.password and parts.hostname and parts.port
    mp.setenv("POSTGRES_SUPERUSER", parts.username)
    mp.setenv("POSTGRES_SUPERUSER_PASSWORD", parts.password)
    mp.setenv("POSTGRES_DB", parts.path.lstrip("/"))
    mp.setenv("POSTGRES_HOST", parts.hostname)
    mp.setenv("POSTGRES_PORT", str(parts.port))
