"""FastAPI application factory (ticket R-20/R-24 boundary — this is where the pieces
built by Tasks 4-10 get assembled into one app; `scripts/bootstrap.py`, Task 12, calls
this after settings/secrets/logging are ready).

The stack itself is not assembled here. `holahost_http.create_edge_app` decides the order
the middleware run in and mounts every router under the base path, because both are
platform rules whose violations are silent (§8.1): a request-id middleware placed below
the body cap logs refusals with no correlation id, a rate limiter placed above
authentication finds no caller, and a router that forgets the prefix is unreachable
through the gateway. What is left below is this service's own values.
"""

from __future__ import annotations

from fastapi import FastAPI
from holahost_auth import HolahostAuthMiddleware
from holahost_http import create_edge_app
from starlette.middleware import Middleware

from interface.http.api_base import API_BASE_URL
from interface.http.dependencies import get_auth_config, get_rate_limiter
from interface.http.edge import (
    HEALTH_PATH,
    MAX_REQUEST_BODY_SIZE,
    MISSING_REQUEST_ID_ERROR,
    REPORTED_UPLOAD_LIMIT,
    bucket_for,
)
from interface.http.errors import ERROR_CONTRACT, SILENT_500_TYPES
from interface.http.health import router as health_router
from interface.http.router import router as documents_router

# Starlette's spool threshold (1 MiB) is left alone deliberately. Raising it to the whole
# request cap would hold every upload in the heap — doubling peak memory per request, times
# the thread pool — to buy the *appearance* of "never touches the disk": heap pages still
# reach it through swap or a core dump, both host settings, and the temp file avoided is
# anonymous on Linux (no name in the filesystem, blocks freed when the fd closes). What the
# service promises is that it never *stores* the file (A-10, §3.8).


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
    return create_edge_app(
        title="rag-documents",
        description=_DESCRIPTION,
        api_base_url=API_BASE_URL,
        routers=[health_router, documents_router],
        # Built here rather than by the factory because the auth library depends on
        # `holahost-http` and not the other way round. Its `public_paths` is the one
        # declaration of what needs no token — the factory reads it back to exempt the same
        # paths from the `X-Request-ID` requirement, and fills in the platform's rejection
        # logger, so all four middleware report a refusal the same way.
        authentication=Middleware(
            HolahostAuthMiddleware,
            config=get_auth_config(),
            public_paths=(HEALTH_PATH,),
        ),
        rate_limiter=get_rate_limiter(),
        bucket_for=bucket_for,
        max_request_body_size=MAX_REQUEST_BODY_SIZE,
        # Enforce the transport cap, advertise the file limit, so the two 413s of §7.6 name
        # one number — see `REPORTED_UPLOAD_LIMIT`.
        reported_body_limit=REPORTED_UPLOAD_LIMIT,
        missing_request_id_error=MISSING_REQUEST_ID_ERROR,
        error_contract=ERROR_CONTRACT,
        silent_500_types=SILENT_500_TYPES,
    )
