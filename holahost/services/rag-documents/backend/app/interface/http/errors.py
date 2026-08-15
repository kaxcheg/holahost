"""Exception -> HTTP envelope mapping (ticket R-22, spec §7.6, §8.6).

Type-based dispatch (not `code`-based): `_STATUS_BY_TYPE` is keyed by exact exception
type, which is what correctly separates `UploadTooLargeError` (413) from
`ParsedTextTooLargeError` (422) despite sharing the wire code `ERR_PAYLOAD_TOO_LARGE`.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from holahost_auth import AuthenticationError, JwksUnavailableError
from starlette.exceptions import HTTPException as StarletteHTTPException

from application.exceptions import (
    ApplicationError,
    DocumentParseError,
    EmptyDocumentError,
    InvalidPayloadError,
    NotFoundError,
    ParsedTextTooLargeError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
    UploadTooLargeError,
)
from application.ports.rate import RateLimitExceededError
from config.logging import log_event

_STATUS_BY_TYPE: dict[type[ApplicationError], int] = {
    UnsupportedMediaTypeError: 415,
    InvalidPayloadError: 422,
    DocumentParseError: 422,
    UploadTooLargeError: 413,
    ParsedTextTooLargeError: 422,
    EmptyDocumentError: 422,
    TooManyChunksError: 422,
    NotFoundError: 404,
}


def _envelope(code: str, message: str, details: Mapping[str, object]) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "details": dict(details)}}


def _duration_ms(request: Request) -> float:
    start = getattr(request.state, "start_time", None)
    return (time.monotonic() - start) * 1000 if start is not None else 0.0


def _log_failure(
    request: Request,
    outcome: str,
    *,
    error_code: str | None = None,
    error_message_sanitized: str | None = None,
) -> None:
    # error_code/error_message_sanitized stay None (and so log as null) for every
    # outcome except the catch-all Exception handler — heterogeneous field presence
    # per op_completed event is already the norm (§8.7: chunk_count/hits/stage_ms are
    # all per-operation-type optional too), not something to avoid here.
    token = getattr(request.state, "token", None)
    log_event(
        "op_completed",
        route=f"{request.method} {request.url.path}",
        outcome=outcome,
        duration_ms=_duration_ms(request),
        request_id=getattr(request.state, "request_id", None),
        client_id=getattr(token, "client_id", None),
        sub=getattr(token, "subject", None),
        error_code=error_code,
        error_message_sanitized=error_message_sanitized,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register every exception -> response mapping this service needs."""

    @app.exception_handler(ApplicationError)
    def handle_application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        status = _STATUS_BY_TYPE.get(type(exc), 500)
        _log_failure(request, outcome=exc.code)
        return JSONResponse(
            status_code=status, content=_envelope(exc.code, str(exc), exc.details_dict())
        )

    @app.exception_handler(RateLimitExceededError)
    def handle_rate_limit(request: Request, exc: RateLimitExceededError) -> JSONResponse:
        _log_failure(request, outcome=exc.code)
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(exc.retry_after)},
            content=_envelope(
                exc.code, "rate limit exceeded", {"retry_after_seconds": exc.retry_after}
            ),
        )

    @app.exception_handler(RequestValidationError)
    def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 422, matching FastAPI's own default for this exception (and RFC 4918's
        # actual definition of the code: syntax/framing is fine, the request's own
        # content doesn't satisfy what's needed) — deliberately not the 400 §7.6's
        # literal wording suggests for "missing field"; see clarifications.md.
        errors = exc.errors()
        field = str(errors[0]["loc"][-1]) if errors else "body"
        _log_failure(request, outcome="ERR_INVALID_PAYLOAD")
        return JSONResponse(
            status_code=422,
            content=_envelope("ERR_INVALID_PAYLOAD", "invalid request payload", {"field": field}),
        )

    @app.exception_handler(AuthenticationError)
    def handle_authentication_error(request: Request, exc: AuthenticationError) -> JSONResponse:
        # holahost-auth raises this directly (not fastapi.HTTPException) — mapping
        # it to a status/response shape is this service's own call (see the
        # library's own README "Errors" section). No envelope, no reason disclosed
        # in the body (US-R07); exc.reason is logged server-side only.
        _log_failure(request, outcome="401", error_code="401", error_message_sanitized=exc.reason)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    @app.exception_handler(JwksUnavailableError)
    def handle_jwks_unavailable(request: Request, exc: JwksUnavailableError) -> JSONResponse:
        # An infra incident (JWKS endpoint down/malformed) must not look like
        # "invalid credentials" to the caller — 503, not 401.
        _log_failure(request, outcome="503", error_code="503", error_message_sanitized=exc.reason)
        return JSONResponse(status_code=503, content={"detail": "Service Unavailable"})

    @app.exception_handler(StarletteHTTPException)
    def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Generic safety net for any HTTPException not covered by a more specific
        # handler above — e.g. Starlette's own routing 404/405 for an unmatched
        # path/method, which is a different fact entirely from application-level
        # NotFoundError ("no such document") and needs no envelope of its own.
        _log_failure(request, outcome=str(exc.status_code))
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers
        )

    @app.exception_handler(Exception)
    def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        _log_failure(
            request,
            outcome="ERR_INTERNAL",
            error_code="ERR_INTERNAL",
            error_message_sanitized=str(exc),
        )
        # Set X-Request-ID here explicitly rather than relying on
        # RequestIdMiddleware's own post-call_next code: Starlette binds a bare
        # `Exception` handler to the outermost ServerErrorMiddleware, *outside*
        # app.add_middleware()'d user middleware (every other handler here is
        # caught by the inner ExceptionMiddleware instead, so this response never
        # flows back out through RequestIdMiddleware.dispatch). request.state is
        # still populated either way — only the header-echo step is skipped.
        request_id = getattr(request.state, "request_id", None)
        headers = {"X-Request-ID": request_id} if request_id is not None else None
        return JSONResponse(
            status_code=500,
            content=_envelope("ERR_INTERNAL", "internal error", {}),
            headers=headers,
        )
