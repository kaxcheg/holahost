"""Request-body size cap, enforced before anything reads the body."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from holahost_http.errors import (
    PayloadTooLargeError,
    RejectionLogger,
    send_platform_error,
)

CONTENT_LENGTH_HEADER = b"content-length"

MULTIPART_OVERHEAD_ALLOWANCE = 64 * 1024
"""What ``multipart/form-data`` framing costs on top of the file itself.

Boundary lines, each part's own headers, the ``name`` field. A fact about the wire
format rather than about any one service's limits, which is why it lives here: every
service that caps an upload needs the same slack above its file limit, and a service
left to guess at it guesses differently each time.
"""


def body_cap_for_upload(max_file_bytes: int) -> int:
    """Whole-request-body cap for a multipart upload of at most ``max_file_bytes``.

    Use this to derive ``BodySizeLimitMiddleware``'s ``max_bytes`` from a service's own
    file-size limit, rather than passing that limit directly. The middleware measures
    the entire request body, framing included, so a cap set to the bare file limit
    rejects a file of exactly that size — a 413 that depends on how many bytes of
    boundary the client happened to send, on an upload the service considers legal.

    The result is an outer bound for the edge, not a replacement for the service's own
    exact check on the file it extracted: that check is what a caller is told it
    exceeded, this one only decides how much gets read before anyone can look.
    """
    return max_file_bytes + MULTIPART_OVERHEAD_ALLOWANCE


class _BodyLimitExceeded(Exception):
    """Internal signal from the counting ``receive`` back to ``__call__``.

    Never escapes this module: the wrapper cannot write a response itself (it is
    called from inside the app, which owns the send channel at that moment), so it
    unwinds the app instead and lets ``__call__`` answer.
    """


class BodySizeLimitMiddleware:
    """Rejects an over-sized request body with 413, without buffering it.

    Two paths, and the second is not optional:

    - **Declared size.** A ``Content-Length`` over the cap is refused immediately,
      before a single byte of body is read.
    - **Undeclared size.** Under ``Transfer-Encoding: chunked`` there is no
      ``Content-Length`` to check, so the body is counted as it streams and the
      request is cut off the moment the running total passes the cap. Without this
      half the cap would be a header check that any client can opt out of by not
      sending the header.

    Why this has to be middleware, not a check inside the handler: a framework
    resolves a multipart form by reading the whole body first — ``await
    request.form()`` runs before any of the endpoint's own dependencies, so
    authentication, rate limiting and every size check written as a dependency all
    happen *after* the upload has already been received in full. Measured before this
    existed: an unauthenticated 50 MiB POST was accepted end to end and only then
    answered 401.

    The cap covers the whole request body, framing included, so a service uploading
    files sets it to its file-size limit plus a small allowance for multipart
    boundaries and part headers. It is therefore a coarse outer bound, not a
    replacement for the service's own exact check on the file it extracted.

    Which is why ``reported_limit`` exists. ``max_bytes`` is an internal transport
    number the caller was never meant to see: a service whose own limit is 8 MiB caps
    the body at 8 MiB + framing, so a rejection here advertised a ``limit`` slightly
    *above* the one the service enforces on the file. A client that trimmed to exactly
    the advertised number got past this middleware and was refused again by the
    service's own check — same status, same code, a different ``limit``. Pass the
    service's file limit as ``reported_limit`` and both gates name one number.

    Args:
        max_bytes: Largest request body accepted, in bytes.
        reported_limit: The limit to put in the error's ``details.limit`` — the
            service's own file-size limit, where that is what the caller is expected
            to act on. Defaults to ``max_bytes``, correct for a service that caps a
            body it does not otherwise check.
        on_rejected: Optional callback used to log a rejection (see
            ``RejectionLogger``).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int,
        reported_limit: int | None = None,
        on_rejected: RejectionLogger | None = None,
    ) -> None:
        self.app = app
        self._max_bytes = max_bytes
        self._reported_limit = max_bytes if reported_limit is None else reported_limit
        self._on_rejected = on_rejected

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = self._declared_length(scope)
        if declared is not None and declared > self._max_bytes:
            # `declared` is the whole body, framing included, so against a
            # `reported_limit` that measures the file it is an upper bound rather than
            # an exact measurement — still the honest answer to "how much did I send",
            # and still strictly above the limit whenever this branch is reached.
            await self._reject(
                scope, receive, send, PayloadTooLargeError(self._reported_limit, declared)
            )
            return

        received = 0
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    raise _BodyLimitExceeded
            return message

        async def watching_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, watching_send)
        except _BodyLimitExceeded:
            if response_started:
                # The app already committed a status line; the connection cannot carry
                # a 413 any more. Nothing left to do but let the failure surface.
                raise
            await self._reject(scope, receive, send, PayloadTooLargeError(self._reported_limit))

    def _declared_length(self, scope: Scope) -> int | None:
        for raw_name, raw_value in scope["headers"]:
            if raw_name.lower() == CONTENT_LENGTH_HEADER:
                try:
                    return int(raw_value)
                except ValueError:
                    # A malformed Content-Length is not this middleware's to judge —
                    # fall through to counting, which needs no cooperation from it.
                    return None
        return None

    async def _reject(
        self, scope: Scope, receive: Receive, send: Send, error: PayloadTooLargeError
    ) -> None:
        if self._on_rejected is not None:
            self._on_rejected(scope, outcome=error.code)
        await send_platform_error(scope, receive, send, status=413, error=error)
