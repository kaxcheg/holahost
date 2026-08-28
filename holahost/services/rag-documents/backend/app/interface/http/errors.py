"""Exception -> HTTP response mapping (ticket R-22, spec §7.6, §8.6).

`ERROR_CONTRACT` is the list of errors this service publishes: membership decides three
things at once — the status the error is answered with, whether the caller learns
anything about it at all, and whether its identity reaches the wire. A class that is not
in it is not one of this service's errors, whatever it is: an unmapped `ApplicationError`
subclass, a `DomainValidationError`, a `KeyError` from a third-party library. All of them
are answered with the same out-of-contract `500 InternalError` and an empty body, which
is what keeps the published vocabulary closed while Python's exception space stays open.

Lookup walks the MRO rather than matching the exact type: an exact-type `dict.get` sends
every unlisted subclass to 500 — silently, with no test or type error to reveal it —
which is not what "dispatch by type" means anywhere else in the framework (Starlette's
own handler registration walks the MRO too).

Covers what is raised from inside a route. The three checks that run *before* routing —
request id, body size, rate limit (§8.1 steps 1-3) — answer for themselves and are not
represented here: FastAPI binds these handlers to Starlette's `ExceptionMiddleware`,
which sits inside the middleware stack, so an exception raised in middleware flies past
every one of them and lands on the 500 handler instead. Their status, envelope and log
line live with the middleware that produces them (`interface/http/edge.py` and
`holahost-http`). Authentication is the same story, in `holahost-auth`. That is why
`MalformedRequestError` has no row below despite being one of this service's own errors:
it is raised and answered by `RequestIdMiddleware`, whose status is an argument at the
point the stack is assembled (`app.py`) — a row here would be a second source for the
same number, with nothing to keep the two equal.

The envelope's shape comes from `holahost-http`, and an error's identity is its own class
name verbatim (`PlatformError.code`). What stays here is only the projection onto HTTP:
which errors are published and with which status. `error_schemas.py` turns this same
table into the response models the routes declare, so `docs/openapi.json` is generated
from it and CI diffs any change to it.
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

    The most-derived ancestor that `ERROR_CONTRACT` lists — which is usually `exc`'s own
    class, and for an unpublished subclass is the published one it derives from. Both
    the status and the identity come from *that* class, not from `exc`: a subclass added
    later has no entry in `docs/openapi.json`, so answering with its own derived code
    would put an identity on the wire that the schema does not describe. It is answered
    as the error it specialises, which the schema does describe.

    `ApplicationError` itself is deliberately absent from `ERROR_CONTRACT`, so the walk
    falls through to `None` for the bare base and for anything that derives from nothing
    published.
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

    `status` is taken as an argument purely to set the log level, and the level is the
    point: every event this service wrote used to go out at `INFO`, while the formatter
    emits a `level` field on every line — so a total outage and a healthy request read
    identically, and the field promised a distinction it never made. `ERROR` for a 5xx,
    `WARNING` for a 4xx (the caller's mistake, not the service's). CloudWatch's filters
    match on `$.outcome`, so no metric moves; what changes is that "show me the errors"
    starts working, here and in any log viewer.

    No `error_code`: `outcome` already is it. Every caller that set one set it to the
    very same value it passed as `outcome` — the field carried no fact of its own, was
    not in §8.7's event schema, and no metric filter reads it. `outcome` is what the 5xx
    and rate-limit filters already match on.

    `error_reason` stays `None` (and logs as null) for every 4xx: there `str(exc)`
    restates `code` for every type but one, and the diagnostic content lives in the
    envelope's `details`. It is populated for every 5xx, where the body deliberately
    carries nothing at all and this line is the only place the cause survives. Passed
    raw: it is the one field `_redact_value` scrubs, and it does so at the sink.
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

    Everything this service did not publish comes back as exactly this — an unmapped
    `ApplicationError` subclass, a `DomainValidationError`, a `KeyError` from a
    third-party library. `InternalError` is the one identity with no class behind it, and
    deliberately so: an `InternalError` exception that nothing ever raises would suggest
    something raises it, when the point is the opposite — this is what a caller is told
    when the answer is "none of the errors above". So the string is written here, once,
    where the response that carries it is built, rather than named as a constant that
    three call sites would import to say the same thing.

    `error_schemas.InternalErrorBody` pins it as a `Literal` on the other side of the
    contract, and `test_openapi` asserts the published document describes it.

    `str(exc)` reaches the log and nothing else: it is the one field `_redact_value`
    scrubs, and the body deliberately carries nothing, so this line is the only place the
    cause survives.
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
            # Not a published error, so neither its identity nor its message may reach
            # the caller: `str(exc)` can only be an internal message, and the identity
            # would name a class the contract does not list. Both go to the log instead.
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

        Both halves of the type land here, and both are 500 for their own reason: an
        unset `field` is an internal defect by definition (`domain/exceptions.py`), and
        a `field`-carrying one that got this far means the use case that was supposed to
        turn it into its §7.6 error did not — also a defect, and not something to answer
        with a guessed 4xx.

        This replaces the `wrap_value_error` decorator that used to sit on every use
        case and re-raise these as a bare `ApplicationError`. The decorator was implicit
        in both directions: easy to leave off a new use case, and — because
        `DomainValidationError` is itself a `ValueError` — it also swallowed the
        client-fixable half, answering 500 where §7.6 says 422, with the `field` lost.

        Its own handler rather than left to `handle_unexpected`: Starlette binds the
        bare-`Exception` handler to `ServerErrorMiddleware`, which re-raises after
        writing the response ("We always continue to raise the exception"), so uvicorn
        then prints an unstructured traceback — outside the JSON log and outside
        `_redact_value`. This one is bound to the inner `ExceptionMiddleware`, which
        does not re-raise.
        """
        return _internal_error(request, exc)

    @app.exception_handler(RequestValidationError)
    def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 422, matching FastAPI's own default for this exception (and RFC 4918's
        # actual definition of the code: syntax/framing is fine, the request's own
        # content doesn't satisfy what's needed) — deliberately not the 400 §7.6's
        # literal wording suggests for "missing field"; see clarifications.md.
        errors = exc.errors()
        field = str(errors[0]["loc"][-1]) if errors else "body"
        # Built from the error itself, not from a literal code and a hand-assembled
        # `details`. Pydantic raised this one, so there is no `InvalidPayloadError` to
        # catch — but answering with a copy of its identity and its `details` shape, kept
        # equal by hand, is how a rename or an added key silently splits one published
        # error into two answers that disagree. `limit` is `None`: a shape violation has
        # no limit to report, and the key is present because the identity is the same.
        error = InvalidPayloadError(field=field)
        _log_failure(request, outcome=error.code, status=ERROR_CONTRACT[InvalidPayloadError])
        return JSONResponse(
            status_code=ERROR_CONTRACT[InvalidPayloadError],
            content=error_envelope(error.code, str(error), error.details_dict()),
        )

    @app.exception_handler(StarletteHTTPException)
    def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Generic safety net for any HTTPException not covered by a more specific
        # handler above — e.g. Starlette's own routing 404/405 for an unmatched
        # path/method, which is a different fact entirely from application-level
        # NotFoundError ("no such document") and needs no envelope of its own.
        _log_failure(request, outcome=str(exc.status_code), status=exc.status_code)
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers
        )

    @app.exception_handler(Exception)
    def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Set X-Request-ID here explicitly rather than relying on
        # RequestIdMiddleware's own post-call_next code: Starlette binds a bare
        # `Exception` handler to the outermost ServerErrorMiddleware, *outside*
        # app.add_middleware()'d user middleware (every other handler here is
        # caught by the inner ExceptionMiddleware instead, so this response never
        # flows back out through RequestIdMiddleware.dispatch). request.state is
        # still populated either way — only the header-echo step is skipped.
        request_id = getattr(request.state, "request_id", None)
        headers = {"X-Request-ID": request_id} if request_id is not None else None
        return _internal_error(request, exc, headers=headers)
