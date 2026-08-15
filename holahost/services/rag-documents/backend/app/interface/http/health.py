"""GET /health (US-R10, §7.5). No auth dependency at all — this is the one route
holahost-auth's own docs and §8.1 explicitly exclude.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text

from application.ports.embedding import EmbeddingModel
from interface.http.dependencies import get_embedding_model, get_engine
from interface.http.schemas import HealthResponse

router = APIRouter()


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
    # at startup (§3.1: model loads before the process serves traffic) — reaching this
    # line already proves it's loaded; no separate readiness flag needed.
    del model
    return HealthResponse(status="ok")
