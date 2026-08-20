from __future__ import annotations

import os

from alembic import context
from pydantic import PostgresDsn
from sqlalchemy import engine_from_config, pool

from infrastructure.db.schema import metadata

config = context.config
target_metadata = metadata


def _dsn() -> str:
    """Builds the psycopg-3 DSN straight from POSTGRES_USER/PASSWORD/DB/HOST/PORT — the same
    components `config.settings.Settings.database_url` builds from, not a pre-assembled
    DATABASE_URL string this module would have to re-parse.

    This module bypasses `scripts.bootstrap`/`Settings` entirely (a standalone alembic entry
    point invoked as `python -m alembic`, not through the app) — pulling in `Settings` itself
    just for a DB DSN would drag in every other unrelated required field (JWKS, chunking,
    rate limits...) too, so it independently reads the same raw env vars `Settings` reads and
    builds via `PostgresDsn.build` the same way: correct percent-encoding of special characters
    in the password, which a shell/f-string interpolation of a pre-built DSN would not have
    given for free (a Secrets-Manager-generated password containing `@`/`:`/`%` would silently
    produce a malformed or wrong-target URL otherwise).

    HOST/PORT default to the fixed `postgres`/5432 convention, matching `docker-compose.yml`'s
    `postgres` service and `Settings.postgres_host`/`postgres_port` — overridden only by
    `tests/integration/conftest.py::_run_migrations`, which points at a testcontainers instance
    on a random host port instead.
    """
    dsn = PostgresDsn.build(
        scheme="postgresql+psycopg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        path=os.environ["POSTGRES_DB"],
    )
    return str(dsn)


def run_migrations_offline() -> None:
    context.configure(url=_dsn(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _dsn()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
