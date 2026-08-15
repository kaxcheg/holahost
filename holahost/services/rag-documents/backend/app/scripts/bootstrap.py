"""Process entrypoint (ticket R-24): secrets -> Settings -> logging -> app, in that
order. Exposes `app` at module level for uvicorn (`uvicorn scripts.bootstrap:app`).
"""

from __future__ import annotations

import os
import time
from typing import cast

from fastapi import FastAPI

from config.logging import configure_logging, log_event
from config.sm_loader import SecretsClient, load_secret_into_env, make_secrets_client
from interface.http.app import create_app
from interface.http.dependencies import get_embedding_model, get_engine, get_settings


def _load_secrets_if_needed() -> None:
    env = os.environ.get("ENV", "dev")
    if env == "dev":
        return  # dev reads DATABASE_URL etc. straight from .env.dev (§3.8)
    # Explicit region, no ambient discovery (sm_loader's own convention) — AWS_REGION
    # is read directly, not through Settings: it's needed before Settings can even be
    # constructed (this runs first in bootstrap()).
    real_client = make_secrets_client(region=os.environ["AWS_REGION"])
    # cast, not a type: ignore — see SecretsClient's docstring (sm_loader.py) for why
    # boto3-stubs' Unpack[TypedDict]-kwargs signature doesn't structurally satisfy this
    # Protocol under mypy despite being call-compatible at the one site that matters.
    client = cast(SecretsClient, real_client)
    load_secret_into_env(env, "db-password", "DATABASE_URL", client)


def bootstrap() -> FastAPI:
    _load_secrets_if_needed()
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
