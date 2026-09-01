"""Process entrypoint: secrets -> settings -> logging -> guards -> app, in that order.

Exposes `app` at module level for uvicorn (`uvicorn scripts.bootstrap:app`).
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI

from config.logging import configure_logging, log_event
from interface.http.api_base import SERVICE_NAME
from interface.http.app import create_app
from interface.http.dependencies import get_settings


def _fetch_secrets_if_needed() -> None:
    """Populate secret-backed environment variables, before `Settings` is built.

    Dev: a no-op — `.env` sets them directly. Staging/prod: fetched fresh on every process
    start, by the instance role.

    A restart alone does not complete every rotation: for a credential the service merely
    *presents*, it does. For one with a second party holding a copy — a database role's
    password, a provider's key — the second party has to be brought into line by a deploy
    step, and the rotation finishes on the next deploy rather than on a restart.
    """
    env = os.environ.get("ENV", "dev")
    if env == "dev":
        return
    import boto3  # lazy: dev never reaches this branch, so it never pays for the import

    # AWS_REGION read directly rather than through Settings: needed before Settings can be
    # constructed. Secret ids are service-scoped: holahost/<env>/<svc>/<name>.
    client = boto3.session.Session().client("secretsmanager", region_name=os.environ["AWS_REGION"])
    for variable, secret in {"POSTGRES_PASSWORD": "db-password"}.items():
        value = client.get_secret_value(SecretId=f"holahost/{env}/{SERVICE_NAME}/{secret}")
        os.environ[variable] = value["SecretString"]


def bootstrap() -> FastAPI:
    _fetch_secrets_if_needed()
    configure_logging()

    start = time.monotonic()
    get_settings()  # fail fast on missing/invalid config before touching anything else

    # Startup guards go here: anything whose failure would otherwise be invisible until a
    # request hits it, and which one query or one check can rule out. `holahost_db`'s
    # `assert_rls_is_enforced(get_engine())` is the usual one for a service whose isolation
    # rests on row-level security.

    app = create_app()
    log_event("startup_completed", duration_ms=(time.monotonic() - start) * 1000)
    return app


app = bootstrap()
