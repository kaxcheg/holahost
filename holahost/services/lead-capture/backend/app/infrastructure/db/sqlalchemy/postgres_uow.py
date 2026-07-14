from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from pydantic import SecretStr
from sqlalchemy import Connection, Engine, create_engine

_POOL_SIZE = 4  # placeholder; pool tuning is deployment-owned (B-46; see __init__)


class PostgresUnitOfWork:
    """Owns the SQLAlchemy engine and the single in-flight transaction (spec §8.2.9).

    Satisfies the ``UnitOfWork`` port structurally (``transaction()``) and additionally folds the
    C-05/C-10 ConnectionProvider role: repositories and the rate limiter run on the current
    in-transaction connection (current-conn-or-raise; no autocommit path). SQLAlchemy Core only —
    no ORM ``Session`` (no identity map / auto-flush), per spec §9.0.
    """

    def __init__(self, database_url: SecretStr) -> None:
        # testcontainers / Neon hand back a plain ``postgresql://`` DSN; SQLAlchemy needs the
        # explicit psycopg-3 dialect. ``-c timezone=utc`` is a CORRECTNESS invariant — it pins the
        # session TZ at connect time (libpq option) so TIMESTAMPTZ round-trips in UTC; no ``SET``
        # statement, so none of the psycopg-pool INTRANS/configure dance. It belongs to the adapter.
        #
        # OPERATIONAL pool tuning does NOT: connection liveness (``pool_pre_ping``), ``pool_recycle``,
        # sizing, and the external-pooler choice (a Neon pooled endpoint / PgBouncer can make
        # client-side pre-ping moot) depend on the deployment topology, not on persistence logic.
        # They are a deployment concern, owned by the bootstrap/B-46 ticket (ideally config-driven
        # per env), and are deliberately NOT decided here. ``_POOL_SIZE`` is a placeholder default.
        url = database_url.get_secret_value().replace("postgresql://", "postgresql+psycopg://", 1)
        self._engine: Engine = create_engine(
            url,
            pool_size=_POOL_SIZE,
            connect_args={"options": "-c timezone=utc"},
        )
        self._current: Connection | None = None

    @property
    def connection(self) -> Connection:
        """The current in-transaction connection.

        :raises RuntimeError: if accessed with no open transaction (programming error — every
            repo/rate call must run inside :meth:`transaction`).
        """
        if self._current is None:
            raise RuntimeError("No active transaction: open uow.transaction() first")
        return self._current

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Open a transactional connection; commit on success, roll back on exception.

        ``Engine.begin()`` is the SQLAlchemy "begin once" boundary — it leases a pooled connection,
        emits BEGIN, and COMMITs on clean exit or ROLLBACKs if the block raises (spec §8.2.9).
        """
        with self._engine.begin() as conn:
            self._current = conn
            try:
                yield
            finally:
                self._current = None

    def close(self) -> None:
        """Dispose the engine and its connection pool.

        Lifecycle: the integration-test ``uow`` fixture calls this on teardown. In production the
        composition root owns it — wired at process/app shutdown by the always-on entrypoint
        (EC2 + FastAPI ``shutdown`` hook); under serverless the engine is reused across warm Lambda
        invocations and is NOT closed per request (the pool is torn down when the execution
        environment is recycled). No current caller exists in the runtime path — bootstrap/DI is a
        later ticket (§8.6 / B-46).
        """
        self._engine.dispose()


if TYPE_CHECKING:
    from application.ports.uow import UnitOfWork

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: PostgresUnitOfWork) -> UnitOfWork:
        return x
