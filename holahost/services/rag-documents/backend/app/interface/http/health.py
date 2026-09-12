"""GET <API_BASE_URL>/health. No auth dependency at all — this is the one route the
platform's authentication middleware excludes.

Under the service's base path like every other route (`interface/http/app.py` applies it), not
at a bare `/health`: the gateway routes `/api/<svc>/*` here *without* rewriting the path, so a
route published at bare `/health` is reachable only from inside the compose network — never
through the gateway, and therefore never by either deploy pipeline's smoke check, which curls
`https://<domain>/api/<svc>/health`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text

from application.ports.embedding import EmbeddingModel
from interface.http.dependencies import get_embedding_model, get_engine
from interface.http.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(
    engine: Annotated[Engine, Depends(get_engine)],
    model: Annotated[EmbeddingModel, Depends(get_embedding_model)],
) -> HealthResponse | JSONResponse:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    # `model` is resolved via the same `@lru_cache` getter `bootstrap.py` calls eagerly
    # at startup, so the model loads before the process serves traffic — reaching this
    # line already proves it's loaded; no separate readiness flag needed.
    del model
    return HealthResponse(status="ok")
