"""Provision the unprivileged role the application connects as (§8.0).

Run once per deploy, as the bootstrap superuser, *after* `alembic upgrade head` and *before*
the container swap — see `.github/actions/ssm-migrate-deploy/action.yml` and the Makefile's
`migrate-*` targets, which are the only callers.

Owner isolation is enforced solely by Postgres RLS (§8.0) — no repository filters by owner in
its own SQL — and a superuser bypasses RLS unconditionally, `FORCE ROW LEVEL SECURITY`
included. The whole guarantee therefore rests on the application connecting as a role that is
not one, while the role the `postgres` container creates at initdb is a superuser by
construction. Hence a separate identity, created here explicitly.

Run every deploy rather than once at initdb, which covers both cases: a fresh database gets the
role created, an existing one gets `ALTER ROLE ... PASSWORD` re-applied — the step that makes a
Secrets Manager rotation take effect, since nothing else in the stack changes that password.

The one place both Postgres identities are held at once, each from its own settings model:
`SuperuserSettings` is the connection it opens, `AppRoleSettings` the role it creates. Not the
app's own `Settings` (same reasoning as `migrations/env.py`): this is a standalone entry point
and would have to supply every unrelated required field it has no business knowing.
"""

from __future__ import annotations

from contextlib import closing

from psycopg import sql
from sqlalchemy import create_engine

from config.settings import AppRoleSettings, SuperuserSettings


def provision() -> None:
    app = AppRoleSettings()
    app_user = app.postgres_user
    app_password = app.postgres_password.get_secret_value()
    role = sql.Identifier(app_user)

    # A plain `create_engine`, not `infrastructure.db.build_engine`: none of what that adds
    # (pool, pre-ping, pgvector registration, UTC connect_args) applies to a handful of one-off
    # DDL statements. The engine is here to own the URL — one DSN spelling for the service.
    engine = create_engine(SuperuserSettings().database_url.get_secret_value())

    # psycopg's `sql` composition on the raw DBAPI connection, not SQLAlchemy `text()` with
    # `String().literal_processor()`. Postgres takes no bind parameters in utility statements
    # (`ALTER ROLE ... PASSWORD %s` is a syntax error), so the password is composed into the
    # statement text — and the two escapers differ there: the literal processor doubles `%`
    # into `%%`, undone only by a DBAPI doing `%`-interpolation, which psycopg skips for a
    # parameterless statement. A password of `a%b` would be stored as `a%%b`, failing every
    # subsequent connection. `sql.Literal` escapes for the server, never for a paramstyle.
    raw = engine.raw_connection()
    try:
        with closing(raw.cursor()) as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE ROLE {} LOGIN").format(role))

            # NOSUPERUSER and NOBYPASSRLS spelled out rather than left to the CREATE ROLE
            # default: they are the entire point of this script, and stating them re-asserts
            # them on every deploy even if someone granted either attribute by hand meanwhile.
            cur.execute(
                sql.SQL(
                    "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE PASSWORD {}"
                ).format(role, sql.Literal(app_password))
            )

            # The tables are owned by the superuser that ran the migrations, so the app role
            # reaches them only through these grants — DML only, no DDL, and notably no
            # ownership: an owner could `ALTER TABLE ... NO FORCE ROW LEVEL SECURITY` or drop
            # the policy outright. ON ALL TABLES re-runs after every `alembic upgrade head`, so
            # tables added by a future migration are covered by the deploy that creates them.
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

    print(f"provisioned app role {app_user!r}: LOGIN NOSUPERUSER NOBYPASSRLS, DML on public")


if __name__ == "__main__":
    provision()
