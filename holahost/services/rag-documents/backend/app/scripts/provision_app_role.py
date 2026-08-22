"""Provision the unprivileged role the application connects as (§8.0).

Run once per deploy, as the bootstrap superuser, *after* `alembic upgrade head` and *before*
the container swap — see `.github/actions/ssm-migrate-deploy/action.yml` and the Makefile's
`migrate-*` targets, which are the only callers.

Why this exists at all: owner isolation in this service is enforced solely by Postgres RLS
(`migrations/versions/20260809_1200_*.py`, §8.0) — no repository filters by owner in its own
SQL. A superuser bypasses RLS unconditionally, `FORCE ROW LEVEL SECURITY` included, so the
whole guarantee rests on the application connecting as a role that is *not* one. The role the
`postgres` container creates at initdb is a superuser by construction (that is what the image's
`POSTGRES_USER` means), which is why docker-compose.yml keeps that bootstrap identity separate
(`postgres`) from the identity the app authenticates as (`POSTGRES_USER` in
`infra/envs/<env>/.env`) and this script creates the latter explicitly.

Running every deploy rather than once, at initdb, is deliberate and covers two things at once:
a fresh database gets the role created, and an existing one gets `ALTER ROLE ... PASSWORD`
re-applied — which is what makes a Secrets Manager rotation actually take effect. Nothing else
in the stack ever changes the role's password: the `postgres` image applies `POSTGRES_PASSWORD`
at initdb only, and the `pgdata` volume outlives every restart.

This is the one place both Postgres identities are held at once, and each comes from its own
settings model rather than raw `os.environ` reads: `SuperuserSettings` is the connection it
opens, `AppRoleSettings` is the role it creates. It reaches Postgres through a SQLAlchemy
engine like every other database access in this service — an earlier direct `psycopg.connect`
was the only consumer that needed a DSN without its driver dialect, and forced that spelling on
all of them.

Deliberately not the app's own `Settings`
(same reasoning as `migrations/env.py`): this is a standalone entry point, and constructing
`Settings` for a DB connection would demand every unrelated required field (JWKS, chunking,
rate limits) it has no way to supply — `AppRoleSettings` is the subset that is genuinely this
script's business, which is why `Settings` inherits it rather than owning it.
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
    # (a five-connection pool, pre-ping, the pgvector type registration, the UTC connect_args)
    # applies to a handful of one-off DDL statements run once per deploy. The engine is here to
    # own the URL — one DSN spelling for the whole service, dialect included — and the work then
    # happens on its own driver connection.
    engine = create_engine(SuperuserSettings().database_url.get_secret_value())

    # psycopg's `sql` composition on the raw DBAPI connection, NOT SQLAlchemy `text()` with
    # `String().literal_processor()`. Postgres accepts no bind parameters in utility statements
    # (`ALTER ROLE ... PASSWORD %s` is a syntax error), so the password has to be composed into
    # the statement text, and the two escapers are not interchangeable for that: SQLAlchemy's
    # literal processor doubles `%` into `%%`, correct only if the result then passes through a
    # DBAPI doing `%`-style interpolation — which psycopg skips for a statement with no
    # parameters. The doubling is then never undone and the role silently gets the wrong
    # password. Caught for real, not reasoned about: a rotation to `a%b` reported success and
    # stored `a%%b`, so every subsequent connection failed to authenticate. `sql.Literal`
    # escapes for the server, never for a paramstyle, and stores `a%b`.
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
