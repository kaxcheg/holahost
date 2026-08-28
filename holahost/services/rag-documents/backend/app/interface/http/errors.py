"""Exception -> HTTP response mapping (spec §7.6, §8.6).

`ERROR_CONTRACT` is the list of errors this service publishes: membership decides the
status, whether the caller learns anything at all, and whether the identity reaches the
wire. Anything absent from it — an unmapped `ApplicationError` subclass, a
`DomainValidationError`, a `KeyError` from a third-party library — is answered with
`500 InternalError` and an empty body, which keeps the published vocabulary closed while
Python's exception space stays open.

Lookup walks the MRO, as Starlette's own handler registration does, so an unlisted
subclass is answered as the published error it specialises instead of silently becoming
a 500.

Covers what is raised inside a route. The checks that run before routing — request id,
body size, rate limit, authentication (§8.1 steps 1-3) — answer for themselves: these
handlers are bound to Starlette's `ExceptionMiddleware`, which sits inside the middleware
stack, so nothing raised in middleware reaches them. That is also why
`MalformedRequestError` has no row here despite being this service's own error: its
status is an argument where the stack is assembled (`app.py`), and a row would be a
second source for the same number.

`error_schemas.py` turns this table into the response models the routes declare, so
`docs/openapi.json` is generated from it and CI diffs any change.
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from holahost_http import error_envelope
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
from config.logging import log_event
from domain.exceptions import DomainValidationError

ERROR_CONTRACT: dict[type[ApplicationError], int] = {
    UnsupportedMediaTypeError: 415,
    InvalidPayloadError: 422,
    DocumentParseError: 422,
    UploadTooLargeError: 413,
    ParsedTextTooLargeError: 422,
    EmptyDocumentError: 422,
    TooManyChunksError: 422,
    NotFoundError: 404,
}


def _published_as(exc: ApplicationError) -> type[ApplicationError] | None:
    """The published error `exc` is answered as, or `None` if there is none.

    Status *and* identity come from the matched ancestor, not from `exc`: a subclass
    added later has no entry in `docs/openapi.json`, so answering with its own name would
    put an identity on the wire that the schema does not describe. `ApplicationError`
    itself is absent from the table, so the bare base falls through to `None`.
    """
    for exc_class in type(exc).__mro__:
        if exc_class in ERROR_CONTRACT:
            return exc_class
    return None


def _duration_ms(request: Request) -> float:
    start = getattr(request.state, "start_time", None)
    return (time.monotonic() - start) * 1000 if start is not None else 0.0


def _log_failure(
    request: Request,
    *,
    outcome: str,
    status: int,
    error_reason: str | None = None,
) -> None:
    """Write the `op_completed` line for a request a handler refused (§8.7).

    `status` is taken only to set the level: `ERROR` for a 5xx, `WARNING` for a 4xx, the
    caller's mistake rather than the service's. CloudWatch filters match on `$.outcome`,
    so the level moves no metric — it makes "show me the errors" work in a log viewer.

    `error_reason` stays `None` for a 4xx, where `str(exc)` restates `code` and the
    diagnostic content is in the envelope's `details`. It is populated for a 5xx, whose
    body deliberately carries nothing, making this line the only place the cause
    survives. Passed raw: `_redact_value` scrubs it at the sink.
    """
    token = getattr(request.state, "token", None)
    log_event(
        "op_completed",
        level=logging.ERROR if status >= 500 else logging.WARNING,
        route=f"{request.method} {request.url.path}",
        outcome=outcome,
        duration_ms=_duration_ms(request),
        request_id=getattr(request.state, "request_id", None),
        client_id=getattr(token, "client_id", None),
        sub=getattr(token, "subject", None),
        error_reason=error_reason,
    )


def _internal_error(
    request: Request, exc: Exception, *, headers: dict[str, str] | None = None
) -> JSONResponse:
    """The out-of-contract answer: `500 InternalError`, empty body, cause to the log.

    `InternalError` is the one identity with no class behind it — an exception nothing
    ever raises would suggest something does, when this is precisely what a caller is
    told when the answer is none of the published errors.
    `error_schemas.InternalErrorBody` pins the same string as a `Literal`.
    """
    code = "InternalError"
    _log_failure(request, outcome=code, status=500, error_reason=str(exc))
    return JSONResponse(
        status_code=500, content=error_envelope(code, "internal error", {}), headers=headers
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register every exception -> response mapping this service needs."""

    @app.exception_handler(ApplicationError)
    def handle_application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        published = _published_as(exc)
        if published is None:
            # Unpublished: `str(exc)` can only be an internal message and the identity
            # would name a class the contract does not list. Both go to the log.
            return _internal_error(request, exc)
        status, code = ERROR_CONTRACT[published], published.__name__
        _log_failure(request, outcome=code, status=status)
        return JSONResponse(
            status_code=status, content=error_envelope(code, str(exc), exc.details_dict())
        )

    @app.exception_handler(DomainValidationError)
    def handle_domain_validation_error(
        request: Request, exc: DomainValidationError
    ) -> JSONResponse:
        """A domain invariant violation that reached this layer untranslated.

        Both halves are 500: an unset `field` is an internal defect by definition
        (`domain/exceptions.py`), and a `field`-carrying one that got this far means the
        use case owing it a §7.6 error did not produce one — also a defect, not something
        to answer with a guessed 4xx.

        Its own handler rather than left to `handle_unexpected`, which Starlette binds to
        `ServerErrorMiddleware`: that one re-raises after writing the response, so uvicorn
        prints an unstructured traceback outside the JSON log and outside `_redact_value`.
        """
        return _internal_error(request, exc)

    @app.exception_handler(RequestValidationError)
    def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 422 rather than the 400 §7.6's wording suggests: framing is fine, the request's
        # own content is not.
        errors = exc.errors()
        field = str(errors[0]["loc"][-1]) if errors else "body"
        # Built from the error itself: Pydantic raised this, so there is no
        # `InvalidPayloadError` to catch, and a hand-copied identity and `details` shape
        # is how one published error silently becomes two answers that disagree.
        error = InvalidPayloadError(field=field)
        _log_failure(request, outcome=error.code, status=ERROR_CONTRACT[InvalidPayloadError])
        return JSONResponse(
            status_code=ERROR_CONTRACT[InvalidPayloadError],
            content=error_envelope(error.code, str(error), error.details_dict()),
        )

    @app.exception_handler(StarletteHTTPException)
    def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Safety net for HTTPExceptions no handler above covers — Starlette's routing
        # 404/405, a different fact from application-level `NotFoundError`.
        _log_failure(request, outcome=str(exc.status_code), status=exc.status_code)
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers
        )

    @app.exception_handler(Exception)
    def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The header is echoed here explicitly: Starlette binds a bare `Exception` handler
        # to the outermost `ServerErrorMiddleware`, outside the user middleware, so this
        # one response never flows back through `RequestIdMiddleware`.
        request_id = getattr(request.state, "request_id", None)
        headers = {"X-Request-ID": request_id} if request_id is not None else None
        return _internal_error(request, exc, headers=headers)
