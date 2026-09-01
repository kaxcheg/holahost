"""GET <API_BASE_URL>/health — the one route authentication is excluded from.

Under the service's base path like every other route (`app.py` applies it), not at a bare
`/health`: the platform gateway routes `/api/<svc>/*` here *without* rewriting the path, so
a route published at bare `/health` is reachable only from inside the compose network —
never through the gateway, and therefore never by either deploy pipeline's smoke check.

What "ready" means is the service's own decision: reachable storage, a loaded model, a
resolvable configuration. What it must not include is anything that costs money or that
fails when a vendor does — health is not the place to discover an upstream outage.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text

from interface.http.dependencies import get_engine
from interface.http.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(engine: Annotated[Engine, Depends(get_engine)]) -> HealthResponse | JSONResponse:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        # No reason in the body: it goes to the log. A readiness probe is read by machines,
        # and by anyone who can reach the endpoint.
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return HealthResponse(status="ok")
