"""X-Request-ID extraction/propagation and request-timer start (spec §3.1, §8.1 step 1)."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Reads `X-Request-ID` (or records its absence) and starts the request timer.

    Applies to every route, including `GET /health` — true ASGI-level middleware wraps
    the whole app uniformly; there is no route-scoped way to exclude a route from it,
    nor a reason to. Never synthesizes a missing header (§3.1: no compensating for the
    absent perimeter with generated headers) — it only ever reads what's already there
    and records the fact when it isn't.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.start_time = time.monotonic()
        request_id = request.headers.get("X-Request-ID")
        request.state.request_id = request_id
        response = await call_next(request)
        if request_id is not None:
            response.headers["X-Request-ID"] = request_id
        return response
