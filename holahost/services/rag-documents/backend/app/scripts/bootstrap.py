"""Process entrypoint (ticket R-24): secrets -> Settings -> logging -> app, in that
order. Exposes `app` at module level for uvicorn (`uvicorn scripts.bootstrap:app`).
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI

from config.logging import configure_logging, log_event
from interface.http.app import create_app
from interface.http.dependencies import get_embedding_model, get_engine, get_settings


def _fetch_password_if_needed() -> None:
    """Set `POSTGRES_PASSWORD` from Secrets Manager, before `Settings` is built (§3.8).

    Dev: no-op — `.env` (`env_file`) already sets `POSTGRES_PASSWORD` directly. Staging/
    prod: fetched here, fresh, on every process start, so a secret rotation takes effect
    on the next restart alone, no redeploy required.

    Only the password: `Settings` itself now assembles the actual connection URL from
    `postgres_user`/`postgres_password`/`postgres_db`/`postgres_host`/`postgres_port`
    (a `@computed_field`, `PostgresDsn`-built) — not this module's job any more. USER/DB
    come from `infra/envs/<env>/.env` (`env_file`) the same way PASSWORD does for dev,
    same file `docker-compose.yml`'s own `postgres` service init already reads.
    """
    env = os.environ.get("ENV", "dev")
    if env == "dev":
        return
    import boto3  # lazy: dev never reaches this branch, so it never pays for the import

    # Explicit region, no ambient discovery — AWS_REGION is read directly, not through
    # Settings: it's needed before Settings can even be constructed. Secret id is
    # service-scoped (`holahost/{env}/rag-documents/db-password`, unlike
    # `~/repos/lead-capture`'s flat `holahost/{env}/{name}`, which predates a second
    # service existing).
    client = boto3.session.Session().client("secretsmanager", region_name=os.environ["AWS_REGION"])
    secret = client.get_secret_value(SecretId=f"holahost/{env}/rag-documents/db-password")
    os.environ["POSTGRES_PASSWORD"] = secret["SecretString"]


def bootstrap() -> FastAPI:
    _fetch_password_if_needed()
    configure_logging()

    start = time.monotonic()
    get_settings()  # fail fast on missing/invalid config before touching anything else
    get_engine()  # build the one process-wide connection pool
    get_embedding_model()  # eager load — §3.1: model must be ready before serving traffic
    load_ms = (time.monotonic() - start) * 1000

    app = create_app()
    log_event("startup_completed", duration_ms=load_ms)
    return app


app = bootstrap()
