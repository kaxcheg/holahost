from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from config.settings import SuperuserSettings
from infrastructure.db.schema import metadata

config = context.config
target_metadata = metadata


def _dsn() -> str:
    """The elevated DSN, from `SuperuserSettings` — not a pre-assembled DATABASE_URL string
    this module would have to re-parse, and not raw `os.environ` reads of its own.

    `SuperuserSettings`, not the app's `Settings`, and not by accident: migrations do
    `CREATE EXTENSION vector` (superuser-only) and `CREATE POLICY`/`ALTER TABLE ... FORCE ROW
    LEVEL SECURITY` (owner-only), while the role the app authenticates as must hold none of
    those privileges — it is the role RLS is meant to constrain, and a role that owns these
    tables could turn its own isolation off (§8.0). Keeping the two identities apart is what
    makes that split real; `scripts/provision_app_role.py` creates the app role and grants it
    plain DML, nothing more.

    This module still bypasses `scripts.bootstrap`/`Settings` entirely (a standalone alembic
    entry point invoked as `python -m alembic`, not through the app): constructing `Settings`
    just for a DSN would demand every unrelated required field (JWKS, chunking, rate limits)
    it has no way to supply. `SuperuserSettings` is the model for exactly this connection and
    nothing else, and it brings the percent-encoding of special characters in the password with
    it — which a shell/f-string interpolation of a pre-built DSN would not have given for free
    (a Secrets-Manager-generated password containing `@`/`:`/`%` would silently produce a
    malformed or wrong-target URL otherwise).

    HOST/PORT default to the fixed `postgres`/5432 convention, matching `docker-compose.yml`'s
    `postgres` service — overridden only by `tests/integration/conftest.py::_run_migrations`,
    which points at a testcontainers instance on a random host port instead.

    """
    return SuperuserSettings().database_url.get_secret_value()


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
