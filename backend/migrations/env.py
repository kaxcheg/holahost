from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from infrastructure.db.sqlalchemy.schema import metadata

config = context.config

_raw_url = os.environ["DATABASE_URL"]
# psycopg 3 SQLAlchemy dialect; testcontainers/Neon give a plain 'postgresql://' DSN.
_url = _raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
config.set_main_option("sqlalchemy.url", _url)

# Single source of truth: the same MetaData drives the Core queries and powers autogenerate of
# future migrations (`alembic revision --autogenerate`).
target_metadata = metadata


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
