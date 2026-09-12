"""Assembling a service's HTTP edge, in the one order that works.

The middleware in this package are independent of each other and each is usable alone.
What is *not* independent is the sequence they run in:

    RequestId -> BodySize -> Auth -> RateLimit -> routing

A service supplies *what* runs, never *when*. This function also mounts every router
under the base path and always registers the exception handlers — two more things whose
omission is silent rather than loud.

Why each position is load-bearing, and why these are middleware rather than dependencies,
is in this package's README.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from fastapi import APIRouter, FastAPI
from starlette.middleware import Middleware

from holahost_http.body_limit import BodySizeLimitMiddleware
from holahost_http.error_handlers import ErrorContract, register_error_handlers
from holahost_http.errors import PlatformError
from holahost_http.observability import log_rejection
from holahost_http.rate_limit import RateLimiter, RateLimitMiddleware
from holahost_http.request_id import RequestIdMiddleware

PUBLIC_PATHS_KWARG = "public_paths"
ON_REJECTED_KWARG = "on_rejected"


def _public_paths_of(authentication: Middleware) -> tuple[str, ...]:
    """The paths the service's authentication middleware was told to skip.

    Read off the middleware rather than taken as a second argument: two lists diverge
    silently in both directions — a path public to authentication but not to the request-id
    requirement answers 422 to a health check, and the reverse opens a route nobody meant to.
    """
    paths = authentication.kwargs.get(PUBLIC_PATHS_KWARG)
    # `Middleware.kwargs` is untyped by construction, so the shape is checked here.
    if not isinstance(paths, Sequence) or isinstance(paths, str):
        raise TypeError(
            f"the authentication middleware must be built with a keyword "
            f"{PUBLIC_PATHS_KWARG}=<sequence of paths> — create_edge_app reads it to exempt "
            f"the same paths from the X-Request-ID requirement"
        )
    return tuple(str(path) for path in paths)


def create_edge_app(
    *,
    title: str,
    description: str,
    api_base_url: str,
    routers: Sequence[APIRouter],
    authentication: Middleware,
    rate_limiter: RateLimiter,
    bucket_for: Callable[[str, str], str | None],
    max_request_body_size: int,
    missing_request_id_error: PlatformError,
    error_contract: ErrorContract,
    silent_500_types: Sequence[type[Exception]] = (),
    reported_body_limit: int | None = None,
    missing_request_id_status: int = 422,
) -> FastAPI:
    """Build the application with the platform's edge already in place.

    Args:
        title: The service's name, as it appears in the generated schema.
        description: What the service is for, plus whatever it wants to tell a consumer
            about its error envelope.
        api_base_url: ``/api/<svc>``. Every router is mounted under it, here and nowhere
            else, so one added later cannot end up outside it by omission.
        routers: The service's routers, health included.
        authentication: ``Middleware(HolahostAuthMiddleware, config=..., public_paths=...,
            on_rejected=...)``. Arrives built because the auth library depends on this one
            and not the other way round; where it sits in the stack is decided here. Its
            ``public_paths`` are also what the request-id requirement exempts.
        rate_limiter: The counter consulted before routing.
        bucket_for: ``(method, path) -> bucket | None``. Matched on the raw path, since it
            runs before routing.
        max_request_body_size: The transport cap, in bytes.
        missing_request_id_error: What this service answers with when ``X-Request-ID`` is
            absent. The requirement is the platform's; its name on the wire is not.
        error_contract: The errors this service publishes and the status each answers
            with. Data rather than a "register the handlers" callback: the function that
            consumes it lives in this package too.
        silent_500_types: Extra types answered ``500`` through an ordinary handler rather
            than Starlette's re-raising bare-``Exception`` one.
        reported_body_limit: What a 413 advertises, where that differs from the transport
            cap because the service checks something inside the body as well.
        missing_request_id_status: The status ``missing_request_id_error`` is answered with.

    Raises:
        TypeError: ``authentication`` was not built with a ``public_paths`` keyword, or was
            built with an ``on_rejected`` — the platform's own is supplied here, so that
            all four middleware report a refusal the same way.
        RuntimeError: ``error_contract`` has no status for ``InvalidPayloadError``.
    """
    public_paths = _public_paths_of(authentication)
    if ON_REJECTED_KWARG in authentication.kwargs:
        raise TypeError(
            f"the authentication middleware must not be built with {ON_REJECTED_KWARG}=... "
            f"— create_edge_app gives every middleware the platform's own rejection logger, "
            f"so that a refusal looks the same whichever of them answered"
        )
    on_rejected = log_rejection
    # Rebuilt rather than mutated: the caller's `Middleware` is theirs. Starlette types the
    # keywords against the middleware class's signature, unknowable here — it is an argument.
    authenticate = Middleware(
        authentication.cls,
        *authentication.args,
        **{ON_REJECTED_KWARG: on_rejected, **authentication.kwargs},  # type: ignore[arg-type]
    )

    app = FastAPI(
        title=title,
        description=description,
        # `middleware=[...]` rather than repeated `add_middleware()` calls: this list is
        # applied outermost-first, in the order it reads, while `add_middleware` prepends.
        middleware=[
            Middleware(
                RequestIdMiddleware,
                missing_header_error=missing_request_id_error,
                status=missing_request_id_status,
                exempt_paths=public_paths,
                on_rejected=on_rejected,
            ),
            Middleware(
                BodySizeLimitMiddleware,
                max_bytes=max_request_body_size,
                reported_limit=reported_body_limit,
                on_rejected=on_rejected,
            ),
            authenticate,
            Middleware(
                RateLimitMiddleware,
                limiter=rate_limiter,
                bucket_for=bucket_for,
                on_rejected=on_rejected,
            ),
        ],
    )
    # Registered here rather than left to the caller: an app with its edge in place and no
    # exception mapping answers 500 to everything the service publishes and looks fine.
    register_error_handlers(app, contract=error_contract, silent_500_types=silent_500_types)
    for router in routers:
        app.include_router(router, prefix=api_base_url)
    return app
