"""Process entrypoint (ticket R-24): secrets -> Settings -> logging -> app, in that
order. Exposes `app` at module level for uvicorn (`uvicorn scripts.bootstrap:app`).
"""

from __future__ import annotations

import os
import time
from typing import cast

from fastapi import FastAPI
from sqlalchemy import Engine, text

from config.logging import configure_logging, log_event
from domain.value_objects.embedding import EMBEDDING_DIM
from infrastructure.embedding.fastembed_embedding_model import FastembedEmbeddingModel
from interface.http.app import create_app
from interface.http.dependencies import get_embedding_model, get_engine, get_settings


def _fetch_password_if_needed() -> None:
    """Set `POSTGRES_PASSWORD` from Secrets Manager, before `Settings` is built (§3.8).

    Dev: no-op — `.env` (`env_file`) already sets `POSTGRES_PASSWORD` directly. Staging/
    prod: fetched here, fresh, on every process start.

    A restart alone is NOT enough to complete a rotation, and this fetch must not be read as
    implying otherwise: it only changes which password the *client* offers. The password the
    Postgres role actually accepts is set by `scripts/provision_app_role.py`, which the deploy
    runs as the bootstrap superuser — the `postgres` image applies `POSTGRES_PASSWORD` at initdb
    and never again, and `pgdata` outlives every restart. Rotating the secret and restarting
    without redeploying therefore fails authentication on every connection. The runbook's
    rotation step is "put-secret-value, then redeploy" for exactly this reason.

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


def _assert_rls_is_enforced(engine: Engine) -> None:
    """Refuse to serve traffic on a connection that bypasses row-level security (§8.0).

    Owner isolation here has exactly one enforcement point — the RLS policies in
    `migrations/versions/20260809_1200_*.py`. No repository filters by owner in its own SQL
    (`SqlAlchemyDocumentsRepo`/`PgvectorSearch` both say so), so if the connecting role is a
    superuser or carries BYPASSRLS, every `get`, `search`, `replace` and `delete` silently
    serves and mutates other owners' rows, with nothing failing anywhere to reveal it.

    That failure mode is invisible by construction, which is why it is checked here rather than
    trusted: the integration suite proves isolation under a deliberately unprivileged role
    (`tests/integration/conftest.py`), so a deployment that connects as something else is not
    covered by any test that passes. One query at startup converts a silent, total loss of
    isolation into a process that refuses to start.
    """
    with engine.connect() as conn:
        bypasses = conn.execute(
            text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        ).scalar_one()
    if bypasses:
        raise RuntimeError(
            "refusing to start: the configured POSTGRES_USER bypasses row-level security "
            "(superuser or BYPASSRLS), which disables owner isolation entirely. Deploy runs "
            "scripts/provision_app_role.py to create this role without either attribute — "
            "check that it ran, and that POSTGRES_USER is not the postgres container's own "
            "initdb superuser."
        )


def _assert_embedding_dimension_matches(model_name: str, actual_dim: int) -> None:
    """Refuse to serve traffic on a model whose vectors do not fit the schema (§3.7).

    `EMBEDDING_MODEL` is environment configuration — a different value per `.env` is a
    supported thing to do — while `EMBEDDING_DIM` is a hardcoded domain constant that
    also fixes the `vector(384)` column and `Embedding`'s own invariant. Nothing tied
    those two together, so pointing the setting at, say, `all-mpnet-base-v2` (768) left
    a process that started cleanly and answered `GET /health` with 200, while every
    single ingest and search failed: `Embedding.__post_init__` raises, `embed_texts`'
    `except Exception` turns it into `EmbeddingFailedError`, and nothing catches that —
    500 `InternalError`, on 100% of traffic, until someone reads a log. `RecursiveTextChunker`
    already fails fast at composition time for the same class of misconfiguration
    (`chunk_window > max_input_tokens`); this is the same guard for the dimension.

    It does NOT cover the other half of a model swap: a *different* model of the same
    384 dimensions passes this check, and its vectors are simply not comparable to the
    ones already stored — searches would return confident nonsense rather than errors.
    Nothing here can detect that; it needs the model identity recorded alongside the
    vectors and a re-embed on change, which the schema has no column for today.
    """
    if actual_dim != EMBEDDING_DIM:
        raise RuntimeError(
            f"refusing to start: EMBEDDING_MODEL={model_name!r} produces {actual_dim}-dimensional "
            f"vectors, but this service stores and searches {EMBEDDING_DIM}-dimensional ones "
            "(domain.value_objects.embedding.EMBEDDING_DIM, and the vector column derived from "
            "it). Every ingest and every search would fail. Point EMBEDDING_MODEL back at a "
            f"{EMBEDDING_DIM}-dimensional model, or migrate the column and the constant together "
            "and re-embed everything already stored."
        )


def bootstrap() -> FastAPI:
    _fetch_password_if_needed()
    configure_logging()

    start = time.monotonic()
    get_settings()  # fail fast on missing/invalid config before touching anything else
    # get_engine() builds the one process-wide connection pool; the guard then spends one
    # query on it proving this deployment's role cannot bypass RLS (see the docstring).
    _assert_rls_is_enforced(get_engine())
    # Eager load — §3.1: the model must be ready before traffic arrives. `cast`, not an
    # isinstance check, same as `dependencies.get_chunker`: `dimension()` is an extra
    # method of the one adapter this getter ever constructs, deliberately not part of
    # the `EmbeddingModel` port (§8.0).
    model = cast(FastembedEmbeddingModel, get_embedding_model())
    _assert_embedding_dimension_matches(get_settings().embedding_model, model.dimension())
    load_ms = (time.monotonic() - start) * 1000

    app = create_app()
    log_event("startup_completed", duration_ms=load_ms)
    return app


app = bootstrap()
