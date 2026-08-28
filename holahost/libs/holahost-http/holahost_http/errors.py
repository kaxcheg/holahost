"""The wire *form* of an error response — not the taxonomy.

Which codes exist, and which HTTP status each one maps to, is a consuming service's
own decision (its spec's error table) and stays in that service. What lives here is
only what every Holahost service must agree on to look like one platform:

- ``error_envelope`` — the JSON shape ``{"error": {code, message, details}}``;
- ``PlatformError`` — the contract that shape is built from (``code`` +
  ``details_dict()``), which a service's own error base class inherits;
- the two errors this library's own middleware raise, and therefore owns.

``PlatformError`` deliberately carries no HTTP status. Status is a protocol fact
decided at the point a response is written: a body rejected unread is a 413, parsed
content that turned out too large is a 422, and two errors may well share one status.
A ``status`` attribute on the exception would force that decision onto the error.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send


class PlatformError(Exception):
    """Base for any exception that becomes an error envelope.

    A service's own error base class inherits this and keeps its own taxonomy:
    subclassing buys the envelope builder, not a set of errors.
    """

    @property
    def code(self) -> str:
        """This error's identity on the wire — its class name, verbatim.

        Not declared beside the class, and not transformed either. An error's identity
        and the shape of its ``details`` are two halves of one contract, and
        ``details_dict()`` already lives on the class, so a ``code`` string declared next
        to it splits that contract across two places kept equal by hand. It buys nothing:
        nothing here or in any service dispatches on ``code``, it is purely an output
        value (status comes from the interface layer's own type -> status table).

        Verbatim rather than mapped to a screaming-snake ``ERR_*`` form, which is what
        this used to do. The mapping added no information and cost the one thing that
        matters when reading a log: the value in the log could no longer be grepped back
        to the class that produced it, because the string existed nowhere in the source.
        It also needed a documented caveat for consecutive capitals (``HTTPError``).

        A class rename is therefore a contract change. That is the point, not a
        drawback: it surfaces as a diff in the service's published schema and fails CI,
        rather than passing as a silent refactor.

        Accessible on the class as ``SomeError.__name__`` wherever an instance is not at
        hand — an interface layer answering an unpublished subclass *as* its published
        ancestor needs exactly that, and now needs no helper for it.
        """
        return type(self).__name__

    def details_dict(self) -> Mapping[str, object]:
        """Wire-format ``details`` payload for this error. Empty by default."""
        return {}


class PayloadTooLargeError(PlatformError):
    """The request body exceeds the cap enforced by ``BodySizeLimitMiddleware``.

    ``actual`` is ``None`` when the size was not known before reading — under
    ``Transfer-Encoding: chunked`` the true size is never learned (the point of the
    middleware is to stop reading), and reporting the partial count would dress a lower
    bound up as a measurement. It is still *present* in ``details``: one identity, one
    set of keys, so a consumer reading ``details.actual`` never has to discover which
    transport the caller happened to use.
    """

    def __init__(self, limit: int, actual: int | None = None) -> None:
        super().__init__("request body too large")
        self.limit = limit
        self.actual = actual

    def details_dict(self) -> Mapping[str, object]:
        return {"limit": self.limit, "actual": self.actual}


class RateLimitExceededError(PlatformError):
    """The caller is over its rate limit for the requested bucket.

    Args:
        retry_after: Seconds to wait before retrying — surfaced by the middleware as
            the mandatory ``Retry-After`` response header.
    """

    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after = retry_after

    def details_dict(self) -> Mapping[str, object]:
        return {"retry_after_seconds": self.retry_after}


def error_envelope(code: str, message: str, details: Mapping[str, object]) -> dict[str, object]:
    """Build the platform's error envelope."""
    return {"error": {"code": code, "message": message, "details": dict(details)}}


class RejectionLogger(Protocol):
    """How a middleware reports a request it rejected before routing.

    Middleware in this library answers a request without ever reaching the service's
    route handlers, so nothing downstream can emit that request's completion log
    line. Rather than log in a shape this library would have to invent (field names,
    event name and allowlist are the service's own observability contract), it calls
    back with the two facts it alone knows and lets the service write the line.

    Optional everywhere it is accepted: a service that has no such contract passes
    nothing and loses only the log line, never the rejection itself.
    """

    def __call__(self, scope: Scope, *, outcome: str, detail: str | None = None) -> None:
        """Record a rejection.

        Args:
            scope: The ASGI scope of the rejected request — carries ``method``,
                ``path`` and whatever earlier middleware left in ``scope["state"]``.
            outcome: The wire code (or status, where there is no code) to report.
            detail: Server-side-only cause, never disclosed to the caller.
        """
        ...


async def send_platform_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    status: int,
    error: PlatformError,
    headers: Mapping[str, str] | None = None,
) -> None:
    """Write ``error`` as an envelope response directly onto the ASGI channel.

    Middleware cannot raise its way to a service's ``@app.exception_handler``: those
    are bound to Starlette's ``ExceptionMiddleware``, which sits *inside* the
    user-middleware stack, so an exception raised in middleware flies straight past
    them to ``ServerErrorMiddleware`` and becomes a 500. Middleware that wants a
    specific status has to produce the response itself, which is what this does.
    """
    response = JSONResponse(
        status_code=status,
        content=error_envelope(error.code, str(error), error.details_dict()),
        headers=dict(headers) if headers else None,
    )
    await response(scope, receive, send)
