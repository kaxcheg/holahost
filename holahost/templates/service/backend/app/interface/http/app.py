"""FastAPI application factory — where the pieces get assembled into one app.

Called by `scripts/bootstrap.py` after settings, secrets and logging are ready.

The stack itself is not assembled here. `holahost_http.create_edge_app` decides the order
the middleware run in and mounts every router under the base path, because both are
platform rules whose violations are silent: a request-id middleware placed below the body
cap logs refusals with no correlation id, a rate limiter placed above authentication finds
no caller, and a router that forgets the prefix is unreachable through the gateway — which
for a health route means the deploy's smoke check never finds it. What is left below is
this service's own values.
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
    bucket_for,
)
from interface.http.errors import ERROR_CONTRACT, SILENT_500_TYPES
from interface.http.health import router as health_router

_DESCRIPTION = """\
<One sentence on what this service is for.>

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
        title="<svc>",
        description=_DESCRIPTION,
        api_base_url=API_BASE_URL,
        routers=[health_router],
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
        # A service that also checks something *inside* the body derives the transport cap
        # from that limit with `body_cap_for_upload` and advertises the inner one here, so
        # a caller told to trim is not refused a second time with a different number.
        missing_request_id_error=MISSING_REQUEST_ID_ERROR,
        error_contract=ERROR_CONTRACT,
        silent_500_types=SILENT_500_TYPES,
    )
