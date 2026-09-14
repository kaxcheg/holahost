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

from holahost_db import SqlAlchemyUnitOfWork, build_engine


def build_test_uow(database_url: str, *, pool_size: int = 5) -> SqlAlchemyUnitOfWork:
    """Build a UoW with its own freshly-built `Engine` from a raw DSN."""
    return SqlAlchemyUnitOfWork(build_engine(database_url, pool_size=pool_size))
