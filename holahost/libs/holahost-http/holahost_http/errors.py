"""The wire *form* of an error response — not the taxonomy.

Which errors exist, and which HTTP status each maps to, is a consuming service's own
decision and stays in that service. Here lives only what every Holahost service must
agree on: the envelope ``{"error": {code, message, details}}``, the ``PlatformError``
contract it is built from, and the two errors this library's own middleware raise.

``PlatformError`` carries no HTTP status: status is decided where a response is written
(a body rejected unread is a 413, parsed content that turned out too large is a 422), and
two errors may share one.
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

        Derived rather than declared beside the class, so the identity and the shape of
        ``details`` cannot drift apart, and a code read in a log greps straight back to
        the class that produced it. A class rename is therefore a contract change, and
        shows up as one in the service's published schema.

        Available on the class as ``SomeError.__name__`` where no instance is at hand.
        """
        return type(self).__name__

    def details_dict(self) -> Mapping[str, object]:
        """Wire-format ``details`` payload for this error. Empty by default."""
        return {}


class PayloadTooLargeError(PlatformError):
    """The request body exceeds the cap enforced by ``BodySizeLimitMiddleware``.

    ``actual`` is ``None`` when the size was not known before reading — under
    ``Transfer-Encoding: chunked`` it never is. The key is still present: one identity,
    one set of keys, so a consumer need not know which transport the caller used.
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


class MalformedRequestError(PlatformError):
    """A request violated the transport contract, with nothing disclosed about how.

    Empty ``details`` on purpose. This is what a service hands
    ``RequestIdMiddleware(missing_header_error=...)``, so it is answered *before*
    authentication, to a caller that by construction arrived by a path it was not meant
    to — every intended entry path attaches ``X-Request-ID`` unconditionally. Naming the
    header would hand exactly that caller the hint needed to get past the check. Same
    discipline as ``401``: the reason is logged, never returned.
    """

    def __init__(self) -> None:
        super().__init__("invalid request")


class InvalidPayloadError(PlatformError):
    """A request field failed validation.

    ``limit`` is always present, ``None`` included: one identity answers with one set of
    keys, and ``None`` says "this field has no length limit", which a caller can read.

    Platform-owned because every service answers it and every service's error handler
    needs a class to build when the framework's own validation rejects a request before
    any route runs — see ``register_error_handlers``.
    """

    def __init__(self, field: str, limit: int | None = None) -> None:
        super().__init__(f"invalid payload: {field}")
        self.field = field
        self.limit = limit

    def details_dict(self) -> Mapping[str, object]:
        return {"field": self.field, "limit": self.limit}


class NotFoundError(PlatformError):
    """The addressed resource does not exist, or belongs to another subject.

    The two cases are deliberately indistinguishable: existence of another subject's
    resource is never disclosed, which is also why ``details`` is empty. A service that
    needs to distinguish them answers ``403`` from its own taxonomy instead.
    """

    def __init__(self, message: str = "not found") -> None:
        super().__init__(message)


INTERNAL_ERROR_CODE = "InternalError"
"""The one identity with no class behind it.

Deliberately not an exception type: a class nobody ever raises would suggest something
does, when the meaning is the opposite — this is what a caller is told when the answer is
none of the errors the service published.
"""


def error_envelope(code: str, message: str, details: Mapping[str, object]) -> dict[str, object]:
    """Build the platform's error envelope.

    ``message`` is carried on the wire for a person reading a log or a response by hand.
    It is **not** part of the contract and is not published in a service's OpenAPI
    document: a consumer branches on ``code`` and composes what it shows from ``details``.
    """
    return {"error": {"code": code, "message": message, "details": dict(details)}}


class RejectionLogger(Protocol):
    """How a middleware reports a request it rejected before routing.

    Middleware here answers without reaching a service's route handlers, so nothing
    downstream can log that request's completion. Field names and event schema are the
    service's own observability contract, so this library hands back the two facts it
    alone knows and lets the service write the line. Optional everywhere it is accepted.
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

    Middleware cannot raise its way to a service's ``@app.exception_handler``: those are
    bound to Starlette's ``ExceptionMiddleware``, which sits *inside* the user-middleware
    stack, so an exception raised in middleware becomes a 500. Middleware that wants a
    specific status has to produce the response itself.
    """
    response = JSONResponse(
        status_code=status,
        content=error_envelope(error.code, str(error), error.details_dict()),
        headers=dict(headers) if headers else None,
    )
    await response(scope, receive, send)
