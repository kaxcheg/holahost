"""FastAPI application factory (ticket R-20/R-24 boundary — this is where the pieces
built by Tasks 4-10 get assembled into one app; `scripts/bootstrap.py`, Task 12, calls
this after settings/secrets/logging are ready).
"""

from __future__ import annotations

from fastapi import FastAPI
from holahost_auth import HolahostAuthMiddleware
from holahost_http import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
)
from starlette.formparsers import MultiPartParser
from starlette.middleware import Middleware

from interface.http.api_base import API_BASE_URL
from interface.http.dependencies import get_auth_config, get_rate_limiter
from interface.http.edge import (
    HEALTH_PATH,
    MAX_REQUEST_BODY_SIZE,
    MISSING_REQUEST_ID_ERROR,
    bucket_for,
    log_rejection,
)
from interface.http.errors import register_error_handlers
from interface.http.health import router as health_router
from interface.http.router import router as documents_router

# Starlette spools each multipart part to a temporary FILE on disk once it passes this
# threshold, which defaults to 1 MiB — well under `MAX_UPLOAD_SIZE`, so §3.8's "uploads
# are held in memory only" was false for most real uploads on the happy path, quietly.
# Raising it to the whole request cap is safe precisely because `BodySizeLimitMiddleware`
# now bounds the body above: the ceiling on what a request can commit to memory is that
# cap, not the caller's imagination. Without the cap this line would be the bug.
MultiPartParser.spool_max_size = MAX_REQUEST_BODY_SIZE


def create_app() -> FastAPI:
    # `middleware=[...]` rather than repeated `app.add_middleware()` calls: this list is
    # read outermost-first, which is the order §8.1 states. `add_middleware` prepends, so
    # the same stack written that way has to be spelled out backwards — and the order is
    # load-bearing, not cosmetic:
    #   request id   outermost, so every refusal below still carries the caller's id;
    #                also §8.1 step 1 — the transport contract, checked before credentials
    #   body size    before ANY of the checks below can be reached, because the framework
    #                reads a multipart body while resolving the endpoint's arguments —
    #                i.e. ahead of its dependencies. Any of this expressed as a Depends()
    #                runs after the upload has already been received in full (measured:
    #                50 MiB accepted end to end, then answered 401).
    #   auth         §8.1 step 2, and the only writer of scope["state"]["token"]
    #   rate limit   §8.1 step 3 — needs that token, so it must sit inside auth
    app = FastAPI(
        title="rag-documents",
        middleware=[
            Middleware(
                RequestIdMiddleware,
                missing_header_error=MISSING_REQUEST_ID_ERROR,
                status=422,
                exempt_paths=(HEALTH_PATH,),
                on_rejected=log_rejection,
            ),
            Middleware(
                BodySizeLimitMiddleware,
                max_bytes=MAX_REQUEST_BODY_SIZE,
                on_rejected=log_rejection,
            ),
            Middleware(
                HolahostAuthMiddleware,
                config=get_auth_config(),
                public_paths=(HEALTH_PATH,),
                on_rejected=log_rejection,
            ),
            Middleware(
                RateLimitMiddleware,
                limiter=get_rate_limiter(),
                bucket_for=bucket_for,
                on_rejected=log_rejection,
            ),
        ],
    )
    register_error_handlers(app)
    # Every router is published under the service's own base path, applied here and nowhere
    # else (see api_base.py) — so a router added later cannot end up outside it by omission.
    app.include_router(health_router, prefix=API_BASE_URL)
    app.include_router(documents_router, prefix=API_BASE_URL)
    return app
