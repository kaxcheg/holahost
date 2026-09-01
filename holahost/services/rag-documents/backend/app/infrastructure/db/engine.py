"""This service's engine: the platform's, plus the one codec its schema needs.

Everything about the pool — size, pre-ping, UTC, the statement and lock timeouts — is
platform policy and lives in `holahost-db`. What is local is the `pgvector` codec, which
has to be registered on **each** raw connection the pool creates: the SQLAlchemy `Vector`
column type is not enough on its own, and a connection made later without it fails at the
first query rather than at startup.
"""

from __future__ import annotations

from typing import Any

from holahost_db import build_engine as build_platform_engine
from pgvector.psycopg import register_vector
from sqlalchemy import Engine


def build_engine(database_url: str, *, pool_size: int = 5) -> Engine:
    """Build the process-shared `Engine` (and its connection pool) from a DSN.

    The composition root builds exactly one per process and hands it to a fresh
    `SqlAlchemyUnitOfWork(engine)` per request.
    """

    def _register_vector(dbapi_connection: Any) -> None:
        register_vector(dbapi_connection)

    return build_platform_engine(database_url, pool_size=pool_size, on_connect=_register_vector)
