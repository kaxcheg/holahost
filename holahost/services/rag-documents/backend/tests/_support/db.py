"""Real (non-fake) database-adapter test helpers.

Unlike `fakes.py`'s in-memory port doubles, this builds an actual
`SqlAlchemyUnitOfWork` against a real DSN — for tests that exercise the adapter
itself (unit-level error-translation checks) or the integration suite's fixtures.
Test-only: the composition root never needs this — it shares one `Engine` per
process and calls `SqlAlchemyUnitOfWork(engine)` directly
(`interface.http.dependencies.get_engine`/`get_uow`).
"""

from __future__ import annotations

from infrastructure.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork, build_engine


def build_test_uow(database_url: str, *, pool_size: int = 5) -> SqlAlchemyUnitOfWork:
    """Build a UoW with its own freshly-built `Engine` from a raw DSN."""
    return SqlAlchemyUnitOfWork(build_engine(database_url, pool_size=pool_size))
