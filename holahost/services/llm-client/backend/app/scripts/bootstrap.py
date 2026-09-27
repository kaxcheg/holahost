"""Process entrypoint: registry -> secrets -> logging -> settings and keys -> app, in that order.

Exposes `app` at module level for uvicorn (`uvicorn scripts.bootstrap:app`).
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI

from config.logging import configure_logging, log_event
from config.provider_keys import key_variable
from interface.http.api_base import SERVICE_NAME
from interface.http.app import create_app
from interface.http.dependencies import (
    get_generation_provider,
    get_providers_repo,
    get_registry,
    get_settings,
)


def _fetch_secrets_if_needed() -> None:
    """Populate secret-backed environment variables, before `Settings` is built.

    Dev: a no-op — `.env` sets them directly. Staging/prod: fetched fresh on every process
    start, by the instance role.

    A restart alone does not complete every rotation: for a credential the service merely
    *presents* — a provider's key, issued by the vendor before it reaches Secrets Manager — it
    does. For one with a second party holding a copy — the database role's password — the
    second party has to be brought into line by a deploy step, and the rotation finishes on the
    next deploy rather than on a restart.
    """
    env = os.environ.get("ENV", "dev")
    if env == "dev":
        return
    import boto3  # lazy: dev never reaches this branch, so it never pays for the import

    # AWS_REGION read directly rather than through Settings: needed before Settings can be
    # constructed. Secret ids are service-scoped: holahost/<env>/llm-client/<name>.
    client = boto3.session.Session().client("secretsmanager", region_name=os.environ["AWS_REGION"])
    # The database password, and one key per enabled provider of the registry, under its
    # `api_key_ref`.
    secrets = {"POSTGRES_PASSWORD": "db-password"}
    secrets.update({key_variable(ref): ref for ref in get_registry().enabled_key_refs().values()})
    for variable, secret in secrets.items():
        value = client.get_secret_value(SecretId=f"holahost/{env}/{SERVICE_NAME}/{secret}")
        os.environ[variable] = value["SecretString"]


def bootstrap() -> FastAPI:
    # The registry first, checked whole: the secrets fetched next are the ones it names, so a
    # broken one stops the start with its own error before any secret is asked for.
    get_providers_repo()
    _fetch_secrets_if_needed()
    configure_logging()

    start = time.monotonic()
    get_settings()  # fail fast on missing/invalid config before touching anything else
    # The provider keys and the chat models built from them, for the same reason: an environment
    # missing a key stops here, not on the first generation.
    get_generation_provider()

    app = create_app()
    log_event("startup_completed", duration_ms=(time.monotonic() - start) * 1000)
    return app


app = bootstrap()
