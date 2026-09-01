"""Row-level security: binding the current subject, and refusing to serve without it.

Optional — only a service whose rows belong to a subject uses this. A service whose table
is a ledger nobody is isolated from (a usage journal read by an operator, say) needs
neither half and should not carry the setting.

What is deliberately **not** here is the policy itself. A migration's SQL is history: it
records what was applied, and a helper that changes later would silently change the meaning
of migrations already run. The recipe is in the README, to be written out in each service's
migration where it can be read next to the table it protects.
"""

from __future__ import annotations

from sqlalchemy import Connection, Engine, text

from holahost_db.translation import translate_db_errors

DEFAULT_OWNER_SETTING = "app.current_owner"


def bind_rls_owner(
    connection: Connection, owner: str, *, setting: str = DEFAULT_OWNER_SETTING
) -> None:
    """Scope the current transaction to ``owner``, for the policies to read.

    ``set_config(..., is_local=true)`` rather than ``SET LOCAL``: Postgres accepts only a
    literal after ``SET LOCAL``, never a bind parameter, so the naive form is a syntax
    error the moment the value is parameterised — and interpolating it instead would put a
    caller-derived string into statement text. ``set_config`` is the parameterised
    equivalent with the same transaction-scoped reset on commit or rollback.

    Called on **every** adapter method rather than once per instance: what it scopes is the
    transaction, and one adapter instance may outlive several.

    ``setting`` is interpolated because Postgres takes no bind parameter for a setting
    name either; it is a code-level constant, never caller data — the caller-derived half,
    ``owner``, is the bound one.
    """
    with translate_db_errors():
        connection.execute(
            text(f"SELECT set_config('{setting}', :owner, true)"),
            {"owner": owner},
        )


def assert_rls_is_enforced(engine: Engine) -> None:
    """Refuse to start on a connection that bypasses row-level security.

    Where isolation has exactly one enforcement point — the policies, with no adapter
    filtering by subject in its own SQL — a connecting role that is a superuser or carries
    ``BYPASSRLS`` silently serves and mutates every other subject's rows.

    Checked rather than trusted because that failure mode is invisible by construction: an
    integration suite proves isolation under a deliberately unprivileged role, so a
    deployment connecting as something else is covered by no passing test. One query at
    startup turns a total loss of isolation into a process that refuses to start.

    Raises:
        RuntimeError: the configured role can bypass RLS.
    """
    with engine.connect() as conn:
        bypasses = conn.execute(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).scalar_one()
    if bypasses:
        raise RuntimeError(
            "refusing to start: the configured Postgres role bypasses row-level security "
            "(superuser or BYPASSRLS), which disables subject isolation entirely. The "
            "deploy's provisioning step creates the application role without either "
            "attribute — check that it ran, and that the application is not connecting as "
            "the database container's own initdb superuser."
        )
