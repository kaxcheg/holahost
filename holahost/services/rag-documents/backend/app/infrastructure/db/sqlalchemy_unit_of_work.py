from __future__ import annotations

from types import TracebackType
from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry

from infrastructure.db.errors import translate_db_errors


def build_engine(database_url: str, *, pool_size: int = 5) -> Engine:
    """Build a process-shared `Engine` (and its connection pool) from a DSN.

    The composition root builds exactly one `Engine` per process and hands it to a fresh
    `SqlAlchemyUnitOfWork(engine)` per request. Tests build their own through
    `tests._support.db.build_test_uow`, so this module has no test-only surface.

    The DSN arrives carrying its driver dialect, so there is nothing to rewrite here.
    """
    engine = create_engine(
        database_url,
        pool_size=pool_size,
        pool_pre_ping=True,
        # §3.7 caps a statement at 5 s; without it a runaway query holds a pooled
        # connection until the client gives up. `lock_timeout` is the tighter of the two
        # deliberately: waiting on a row lock is queueing behind someone else's
        # transaction, and `replace`/`delete` take that lock (§8.6), so failing fast turns
        # a pile-up into retryable errors instead of a pool exhausted by waiters. Both
        # surface as `ConcurrentUpdateError` (`db/errors.py`), which §8.6 declares
        # retryable.
        #
        # Migrations are unaffected: `migrations/env.py` builds its own engine, and DDL
        # that legitimately runs longer must not be cut off.
        connect_args={"options": "-c timezone=utc -c statement_timeout=5000 -c lock_timeout=2000"},
    )

    @event.listens_for(engine, "connect")
    def _register_vector_type(
        dbapi_connection: psycopg.Connection[Any], connection_record: ConnectionPoolEntry
    ) -> None:
        # Required even with the SQLAlchemy `Vector` column type: the codec still needs
        # registering on each raw psycopg3 connection the pool creates (pgvector-python's
        # documented pattern for sync SQLAlchemy + psycopg3).
        register_vector(dbapi_connection)

    return engine


class SqlAlchemyUnitOfWork:
    """Owns the engine and the single in-flight transaction (application port `UnitOfWork`).

    Repositories and `PgvectorSearch` are constructed with a reference to *this exact
    instance* and read `.active_connection` for every call — there is no standalone
    fallback: the application layer wraps every port call in `with uow:` (§8.0), so a
    connection is always active when a repo method runs.
    Re-entrant across sequential (not nested) `with self:` blocks in the same request,
    e.g. UC-R2's separate pre-check and locked-write transactions.
    """

    def __init__(self, engine: Engine) -> None:
        """Build a lightweight UoW around an already-built `Engine`.

        Cheap: no pool construction happens here, just wrapping — safe to build fresh
        for every request under threadpool concurrency (ADR A-9). The composition root
        (`interface.http.dependencies.get_engine`) builds one `Engine` per process and
        passes it to a fresh instance of this class per request. Never call
        `.dispose()` on an instance wrapping a *shared* engine — that disposes it for
        every other holder too; only the process-owning `get_engine()` singleton
        should ever be disposed, at shutdown.
        """
        self._engine = engine
        self.active_connection: Connection | None = None

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        with translate_db_errors():
            self.active_connection = self._engine.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.active_connection is None:
            raise RuntimeError("uow.__exit__ called without __enter__")
        conn = self.active_connection
        try:
            with translate_db_errors():
                if exc_type is None:
                    conn.commit()
                else:
                    conn.rollback()
        finally:
            conn.close()
            self.active_connection = None

    def commit(self) -> None:
        if self.active_connection is None:
            raise RuntimeError("commit() outside an active transaction")
        with translate_db_errors():
            self.active_connection.commit()

    def rollback(self) -> None:
        if self.active_connection is None:
            raise RuntimeError("rollback() outside an active transaction")
        with translate_db_errors():
            self.active_connection.rollback()

    def dispose(self) -> None:
        """Dispose the engine and its connection pool (test/process-shutdown lifecycle)."""
        self._engine.dispose()
