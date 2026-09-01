from __future__ import annotations

from holahost_db.alembic_support import run_migrations

from infrastructure.db.schema import metadata

# The whole of this service's Alembic entry point: the one thing that is its own is the
# schema. Everything else — the elevated DSN from `SuperuserSettings` (migrations run DDL
# the application's role must not hold), building it from the settings model so a
# generated password is encoded correctly, `NullPool` for a one-shot process, and the
# offline/online split — is the platform's and lives in `holahost_db.alembic_support`.
run_migrations(metadata)
