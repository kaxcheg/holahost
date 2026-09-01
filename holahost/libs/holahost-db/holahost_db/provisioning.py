"""Create (or re-assert) the unprivileged role the application connects as.

Run once per deploy, as the bootstrap superuser, *after* the migrations and *before* the
container swap. Idempotent by construction: a fresh database gets the role created, an
existing one gets ``ALTER ROLE ... PASSWORD`` re-applied — which is the step that makes a
Secrets Manager rotation take effect, since nothing else in the stack changes that
password. That is why a restart alone never completes a rotation: it changes only what the
client *offers*.
"""

from __future__ import annotations

from contextlib import closing

from psycopg import sql
from sqlalchemy import create_engine


def provision_app_role(*, superuser_url: str, app_user: str, app_password: str) -> None:
    """Create ``app_user`` if absent, then re-assert its attributes, password and grants.

    ``NOSUPERUSER`` and ``NOBYPASSRLS`` are spelled out rather than left to the
    ``CREATE ROLE`` default: for a service whose isolation rests on row-level security they
    are the entire point, and stating them re-asserts them on every deploy even if someone
    granted either attribute by hand meanwhile.

    The grants are DML only — no DDL, and notably no ownership: an owner could
    ``ALTER TABLE ... NO FORCE ROW LEVEL SECURITY`` or drop a policy outright.
    ``ON ALL TABLES`` re-runs after every ``alembic upgrade head``, so a table added by a
    future migration is covered by the deploy that creates it.
    """
    role = sql.Identifier(app_user)

    # A plain `create_engine`, not `build_engine`: none of what that adds — pool,
    # pre-ping, statement timeouts, per-connection codecs — applies to a handful of one-off
    # DDL statements, and a statement timeout would be actively wrong here. The engine is
    # present to own the URL, so there is one DSN spelling for the service.
    engine = create_engine(superuser_url)

    # psycopg's `sql` composition on the raw DBAPI connection, not SQLAlchemy `text()` with
    # `String().literal_processor()`. Postgres takes no bind parameters in utility
    # statements (`ALTER ROLE ... PASSWORD %s` is a syntax error), so the password is
    # composed into the statement text — and the two escapers differ exactly there: the
    # literal processor doubles `%` into `%%`, undone only by a DBAPI doing
    # `%`-interpolation, which psycopg skips for a parameterless statement. A password of
    # `a%b` would be stored as `a%%b`, failing every subsequent connection. `sql.Literal`
    # escapes for the server, never for a paramstyle.
    raw = engine.raw_connection()
    try:
        with closing(raw.cursor()) as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE ROLE {} LOGIN").format(role))

            cur.execute(
                sql.SQL(
                    "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE PASSWORD {}"
                ).format(role, sql.Literal(app_password))
            )
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            cur.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
                ).format(role)
            )
        raw.commit()
    finally:
        raw.close()
    engine.dispose()
