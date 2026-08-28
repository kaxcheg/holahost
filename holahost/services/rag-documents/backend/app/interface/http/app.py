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
from starlette.middleware import Middleware

from interface.http.api_base import API_BASE_URL
from interface.http.dependencies import get_auth_config, get_rate_limiter
from interface.http.edge import (
    HEALTH_PATH,
    MAX_REQUEST_BODY_SIZE,
    MISSING_REQUEST_ID_ERROR,
    REPORTED_UPLOAD_LIMIT,
    bucket_for,
    log_rejection,
)
from interface.http.errors import register_error_handlers
from interface.http.health import router as health_router
from interface.http.router import router as documents_router

# Starlette's own spool threshold (1 MiB) is left alone, deliberately — this module used
# to raise `MultiPartParser.spool_max_size` to the whole-request cap so that §3.8's
# "uploads are held in memory only" would be true. It bought the appearance of that
# property, not the property: an upload kept in the heap still reaches the disk through
# swap or a core dump, both host settings this repository does not own, and the temp file
# it avoided is anonymous on Linux (`SpooledTemporaryFile` rolls over to
# `tempfile.TemporaryFile` — no name in the filesystem, blocks freed by the kernel when
# the fd closes, crash included). What it did cost was real: the parser held the whole
# file, `_read_upload`'s copy held it again, and an 8 MiB upload peaked at ~16 MiB before
# parsing started — times the thread pool, with no ingest concurrency limit under it.
# What the service actually promises is that it never *stores* the file (A-10): no bucket,
# no column, no path. Keeping plaintext off the disk entirely is a host-level posture (no
# swap, no dumps, encrypted volume) and belongs where the instance is defined.


_DESCRIPTION = """\
Ingestion and semantic search over a subject's own documents.

Errors answer `{"error": {"code", "message", "details"}}`. Branch on `code`: it is the
error's identity and it tags `details`, whose shape depends on it. `message` is for a
person reading a log — do not parse it, and compose what you show a user from `code` and
`details`. The HTTP status is a projection of the identity, not a separate fact.

Only this service's own errors are described below. What the shared edge answers with —
`401`/`503` for authentication, `429` over the rate limit, `413` for a request body past
the transport cap — belongs to the platform contract and is the same for every service
behind it.
"""


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
        description=_DESCRIPTION,
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
                # Enforce the transport cap, advertise the file limit — see
                # `REPORTED_UPLOAD_LIMIT`. Without it the two 413s of §7.6 named two
                # different numbers.
                reported_limit=REPORTED_UPLOAD_LIMIT,
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
