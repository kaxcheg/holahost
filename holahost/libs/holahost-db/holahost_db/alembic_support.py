"""What every service's ``migrations/env.py`` does, minus its ``MetaData``.

The DSN comes from ``SuperuserSettings`` and not from the application's own settings, and
that is a rule rather than a convenience: migrations run DDL the application's role must
not hold — creating extensions, creating policies, forcing row-level security on a table —
while that role is the one those policies exist to constrain. A role that owned these
tables could turn its own isolation off.

Building it from the settings model rather than reading a pre-assembled ``DATABASE_URL``
brings the percent-encoding of a generated password with it, which a shell or f-string
interpolation would not.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import MetaData, engine_from_config, pool

from holahost_db.settings import SuperuserSettings


def run_migrations(target_metadata: MetaData) -> None:
    """Run Alembic in whichever mode the invocation asked for.

    Called at import time from a service's ``migrations/env.py``, which is the whole of
    that file besides the one import naming its schema.
    """
    dsn = SuperuserSettings().database_url.get_secret_value()

    if context.is_offline_mode():
        context.configure(url=dsn, target_metadata=target_metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    configuration = context.config.get_section(context.config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = dsn
    # NullPool: a migration run is one connection for the life of a short process, so
    # pooling buys nothing and leaves connections open past the work.
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
