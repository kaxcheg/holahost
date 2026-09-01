"""The process-wide engine, and the per-request transaction taken from it."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry

from holahost_db.translation import translate_db_errors

DEFAULT_STATEMENT_TIMEOUT_MS = 5_000
DEFAULT_LOCK_TIMEOUT_MS = 2_000
"""`lock_timeout` is the tighter of the two deliberately. Waiting on a row lock is queueing
behind someone else's transaction, so failing fast turns a pile-up into retryable errors
instead of a pool exhausted by waiters — and both surface as `ConcurrentUpdateError`,
which the retry helper is built for."""


def build_engine(
    database_url: str,
    *,
    pool_size: int = 5,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    on_connect: Callable[[Any], None] | None = None,
) -> Engine:
    """Build the process-shared ``Engine`` (and its connection pool) from a DSN.

    A composition root builds exactly one per process and hands it to a fresh
    ``SqlAlchemyUnitOfWork(engine)`` per request. The DSN arrives carrying its driver
    dialect, so there is nothing to rewrite here.

    Timeouts are set on the session rather than left to the server default: without them a
    runaway query holds a pooled connection until the client gives up. Migrations are
    unaffected — they build their own engine, and DDL that legitimately runs longer must
    not be cut off.

    Args:
        on_connect: Run against every raw DBAPI connection the pool creates. This is where
            a per-connection type codec is registered (``pgvector``'s, for instance):
            registering it once on the engine is not enough, each new connection needs it.
    """
    engine = create_engine(
        database_url,
        pool_size=pool_size,
        pool_pre_ping=True,
        connect_args={
            "options": (
                f"-c timezone=utc -c statement_timeout={statement_timeout_ms} "
                f"-c lock_timeout={lock_timeout_ms}"
            )
        },
    )

    if on_connect is not None:
        hook = on_connect

        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_connection: Any, connection_record: ConnectionPoolEntry) -> None:
            hook(dbapi_connection)

    return engine


class SqlAlchemyUnitOfWork:
    """Owns one in-flight transaction on a shared engine (the ``UnitOfWork`` port).

    Adapters are constructed with a reference to *this exact instance* and read
    ``.active_connection`` on every call: the application layer wraps every port call in
    ``with uow:``, so a connection is always active when an adapter method runs, and there
    is no standalone-connection fallback to keep working.

    Re-entrant across sequential — not nested — ``with`` blocks in one request, which is
    what a use case doing a cheap pre-check and then a locked write needs.
    """

    def __init__(self, engine: Engine) -> None:
        """Wrap an already-built ``Engine``.

        Cheap: no pool construction happens here, so this is safe to build fresh for every
        request under threadpool concurrency. Never call ``dispose()`` on an instance
        wrapping a *shared* engine — that disposes it for every other holder too; only the
        composition root that owns the engine should dispose it, at shutdown.
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

    def connection(self) -> Connection:
        """The active connection, for an adapter running inside ``with uow:``.

        Raises:
            RuntimeError: called outside a transaction — a wiring defect, since every port
                call is contracted to happen inside one.
        """
        if self.active_connection is None:
            raise RuntimeError("no active transaction")
        return self.active_connection
