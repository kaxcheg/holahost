"""Process entrypoint: secrets -> Settings -> logging -> app, in that order. Exposes
`app` at module level for uvicorn (`uvicorn scripts.bootstrap:app`).
"""

from __future__ import annotations

import os
import time
from typing import cast

from fastapi import FastAPI
from holahost_db import assert_rls_is_enforced

from config.logging import configure_logging, log_event
from domain.value_objects.embedding import EMBEDDING_DIM
from infrastructure.embedding.fastembed_embedding_model import FastembedEmbeddingModel
from interface.http.app import create_app
from interface.http.dependencies import get_embedding_model, get_engine, get_settings


def _fetch_password_if_needed() -> None:
    """Set `POSTGRES_PASSWORD` from Secrets Manager, before `Settings` is built.

    Dev: no-op — `.env` sets `POSTGRES_PASSWORD` directly. Staging/prod: fetched fresh on
    every process start.

    A restart alone does not complete a rotation: this only changes which password the
    *client* offers. What the role accepts is set by `scripts/provision_app_role.py`,
    which the deploy runs as the bootstrap superuser (the `postgres` image applies
    `POSTGRES_PASSWORD` at initdb and never again, and `pgdata` outlives restarts). Hence
    the runbook's "put-secret-value, then redeploy".

    Only the password: `Settings` assembles the connection URL from its own fields.
    """
    env = os.environ.get("ENV", "dev")
    if env == "dev":
        return
    import boto3  # lazy: dev never reaches this branch, so it never pays for the import

    # AWS_REGION read directly rather than through Settings: needed before Settings can
    # be constructed. The secret id is service-scoped.
    client = boto3.session.Session().client("secretsmanager", region_name=os.environ["AWS_REGION"])
    secret = client.get_secret_value(SecretId=f"holahost/{env}/rag-documents/db-password")
    os.environ["POSTGRES_PASSWORD"] = secret["SecretString"]


def _assert_embedding_dimension_matches(model_name: str, actual_dim: int) -> None:
    """Refuse to serve traffic on a model whose vectors do not fit the schema.

    `EMBEDDING_MODEL` is per-environment configuration, while `EMBEDDING_DIM` is a domain
    constant that also fixes the `vector(384)` column and `Embedding`'s invariant. Without
    this guard, pointing the setting at a 768-dimensional model starts cleanly, answers
    `GET /health` with 200, and turns every ingest and search into a 500. The chunker
    fails fast on the analogous `chunk_window > max_input_tokens`.

    It does NOT cover the other half of a model swap: a different model of the same 384
    dimensions passes, and its vectors are not comparable to those already stored —
    searches return confident nonsense rather than errors. Detecting that needs the model
    identity stored alongside the vectors, which the schema has no column for.
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
    # get_engine() builds the one process-wide pool; the guard spends one query on it.
    # Owner isolation here has exactly one enforcement point — the RLS policies the
    # migrations applied — so a role that bypasses them serves every other owner's rows
    # while every test still passes.
    assert_rls_is_enforced(get_engine())
    # Eager load, so the model is ready before traffic arrives. `cast` rather than an
    # isinstance check: `dimension()` is an extra method of the one adapter this getter
    # constructs, deliberately outside the `EmbeddingModel` port.
    model = cast(FastembedEmbeddingModel, get_embedding_model())
    _assert_embedding_dimension_matches(get_settings().embedding_model, model.dimension())
    load_ms = (time.monotonic() - start) * 1000

    app = create_app()
    log_event("startup_completed", duration_ms=load_ms)
    return app


app = bootstrap()
