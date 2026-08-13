from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from infrastructure.db.schema import metadata

config = context.config
target_metadata = metadata


def _dsn() -> str:
    dsn = os.environ["DATABASE_URL"]
    # Alembic/SQLAlchemy need the explicit psycopg-3 dialect; testcontainers and a
    # plain `.env` DSN both hand back bare "postgresql://".
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


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
