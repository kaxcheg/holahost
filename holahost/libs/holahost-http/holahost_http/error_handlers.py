"""Exception -> HTTP response mapping, shared by every Holahost service.

The machinery is the platform's; the vocabulary is the service's. A service passes its
``contract`` — the errors it publishes and the status each answers with — and membership in
it decides the status, whether the caller learns anything, and whether the identity reaches
the wire. Anything absent is answered ``500 InternalError`` with an empty body, which keeps
the published vocabulary closed while Python's exception space stays open.

Covers what is raised inside a route. The checks that run *before* routing — request id,
body size, rate limit, authentication — answer for themselves: these handlers are bound to
Starlette's ``ExceptionMiddleware``, which sits inside the middleware stack, so nothing
raised in middleware reaches them.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from holahost_observability import OP_COMPLETED, log_event
from starlette.exceptions import HTTPException as StarletteHTTPException

from holahost_http.errors import (
    INTERNAL_ERROR_CODE,
    InvalidPayloadError,
    PlatformError,
    error_envelope,
)

ErrorContract = Mapping[type[PlatformError], int]
"""What a service publishes: its own error classes, each mapped to a status.

Not a status *per error family* — two errors may answer the same status, and changing a
status is a change to this table alone, never to an exception class.
"""


def _published_as(exc: PlatformError, contract: ErrorContract) -> type[PlatformError] | None:
    """The published error ``exc`` is answered as, or ``None`` if there is none.

    Walks the MRO, as Starlette's own handler registration does. Status *and* identity
    come from the matched ancestor, not from ``exc``: a subclass added later has no entry
    in the service's published schema, so answering with its own name would put an
    identity on the wire that the schema does not describe.
    """
    for exc_class in type(exc).__mro__:
        if exc_class in contract:
            return exc_class
    return None


def _duration_ms(request: Request) -> float:
    start = getattr(request.state, "start_time", None)
    return (time.monotonic() - start) * 1000 if start is not None else 0.0


def register_error_handlers(
    app: FastAPI,
    *,
    contract: ErrorContract,
    silent_500_types: Sequence[type[Exception]] = (),
) -> None:
    """Register every exception -> response mapping a service needs.

    Args:
        app: The application to register on.
        contract: This service's published errors and their statuses.
        silent_500_types: Extra exception types answered ``500 InternalError`` through an
            ordinary handler, keeping them out of Starlette's bare-``Exception`` path: that
            one is bound to ``ServerErrorMiddleware``, which **re-raises** after writing the
            response, so uvicorn prints a traceback outside the JSON log and its scrubbing.

    Raises:
        RuntimeError: ``contract`` has no entry for ``InvalidPayloadError``. Framework
            validation can reject a request before any route runs — on a path or query
            parameter too — and this is what it is answered with. Checked at registration.
    """
    if InvalidPayloadError not in contract:
        raise RuntimeError(
            "contract has no status for InvalidPayloadError — it is what a "
            "RequestValidationError is answered with, so every service must publish it"
        )
    invalid_payload_status = contract[InvalidPayloadError]

    def log_failure(
        request: Request, *, outcome: str, status: int, error_reason: str | None = None
    ) -> None:
        """Write the completion event for a request a handler refused.

        ``status`` only sets the level: ``ERROR`` for a 5xx, ``WARNING`` for a 4xx. Metric
        filters match ``$.outcome``, so the level moves no metric — it is for a person.

        ``error_reason`` stays ``None`` for a 4xx, where the diagnostic content is already
        in the envelope's ``details``, and is populated for a 5xx, whose body carries
        nothing. Passed raw — the scrubber runs at the sink.
        """
        token = getattr(request.state, "token", None)
        log_event(
            OP_COMPLETED,
            level=logging.ERROR if status >= 500 else logging.WARNING,
            route=f"{request.method} {request.url.path}",
            outcome=outcome,
            duration_ms=_duration_ms(request),
            request_id=getattr(request.state, "request_id", None),
            client_id=getattr(token, "client_id", None),
            sub=getattr(token, "subject", None),
            error_reason=error_reason,
        )

    def internal_error(
        request: Request, exc: Exception, *, headers: dict[str, str] | None = None
    ) -> JSONResponse:
        log_failure(request, outcome=INTERNAL_ERROR_CODE, status=500, error_reason=str(exc))
        return JSONResponse(
            status_code=500,
            content=error_envelope(INTERNAL_ERROR_CODE, "internal error", {}),
            headers=headers,
        )

    @app.exception_handler(PlatformError)
    def handle_platform_error(request: Request, exc: PlatformError) -> JSONResponse:
        published = _published_as(exc, contract)
        if published is None:
            # Unpublished: `str(exc)` can only be an internal message, and the identity
            # would name a class the contract does not list. Both go to the log.
            return internal_error(request, exc)
        status, code = contract[published], published.__name__
        log_failure(request, outcome=code, status=status)
        return JSONResponse(
            status_code=status, content=error_envelope(code, str(exc), exc.details_dict())
        )

    for silent_type in silent_500_types:

        @app.exception_handler(silent_type)
        def handle_silent_500(request: Request, exc: Exception) -> JSONResponse:
            return internal_error(request, exc)

    @app.exception_handler(RequestValidationError)
    def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 422 rather than 400: by RFC 9110 §15.5.1 a 400 is broken syntax or framing,
        # while 422 (RFC 4918 §11.2) is a syntactically correct request whose content
        # could not be processed. Matches FastAPI's own default status for this error.
        errors = exc.errors()
        field = str(errors[0]["loc"][-1]) if errors else "body"
        # Built from the error itself: Pydantic raised this, so there is no
        # `InvalidPayloadError` to catch, and a hand-copied identity and `details` shape
        # is how one published error silently becomes two answers that disagree.
        error = InvalidPayloadError(field=field)
        log_failure(request, outcome=error.code, status=invalid_payload_status)
        return JSONResponse(
            status_code=invalid_payload_status,
            content=error_envelope(error.code, str(error), error.details_dict()),
        )

    @app.exception_handler(StarletteHTTPException)
    def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Safety net for HTTPExceptions no handler above covers — Starlette's routing
        # 404/405, a different fact from an application-level `NotFoundError`.
        log_failure(request, outcome=str(exc.status_code), status=exc.status_code)
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers
        )

    @app.exception_handler(Exception)
    def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The header is echoed explicitly here: Starlette binds a bare `Exception`
        # handler to the outermost `ServerErrorMiddleware`, outside the user middleware,
        # so this one response never flows back through `RequestIdMiddleware`.
        request_id = getattr(request.state, "request_id", None)
        headers = {"X-Request-ID": request_id} if request_id is not None else None
        return internal_error(request, exc, headers=headers)
