"""Provision the unprivileged role the application connects as.

Run once per deploy, as the bootstrap superuser, *after* `alembic upgrade head` and
*before* the container swap — see `.github/actions/ssm-migrate-deploy/action.yml` and the
Makefile's `migrate-*` targets, which are the only callers.

Owner isolation here rests solely on Postgres RLS, and a superuser bypasses RLS
unconditionally. The role the `postgres` container creates at initdb is a superuser by
construction, so the application needs a separate identity that is not — created here.

This file is the one place both Postgres identities are held at once, each from its own
settings model. The statements themselves are the platform's
(`holahost_db.provision_app_role`), because the split between the role that owns a schema
and the role that serves traffic is not this service's invention.
"""

from __future__ import annotations

from holahost_db import AppRoleSettings, SuperuserSettings, provision_app_role


def provision() -> None:
    # Not the app's own `Settings` (same reasoning as `migrations/env.py`): this is a
    # standalone entry point and would have to supply every unrelated required field it
    # has no business knowing.
    app = AppRoleSettings()

    provision_app_role(
        superuser_url=SuperuserSettings().database_url.get_secret_value(),
        app_user=app.postgres_user,
        app_password=app.postgres_password.get_secret_value(),
    )

    print(
        f"provisioned app role {app.postgres_user!r}: "
        "LOGIN NOSUPERUSER NOBYPASSRLS, DML on public"
    )


if __name__ == "__main__":
    provision()
