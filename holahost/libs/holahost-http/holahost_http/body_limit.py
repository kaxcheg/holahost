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
"""What ``multipart/form-data`` framing costs on top of the file itself — boundary
lines, part headers, the ``name`` field. A fact about the wire format, not about any
service's limits, so every service that caps an upload uses the same slack."""


def body_cap_for_upload(max_file_bytes: int) -> int:
    """Whole-request-body cap for a multipart upload of at most ``max_file_bytes``.

    Derive ``BodySizeLimitMiddleware``'s ``max_bytes`` with this rather than passing a
    file limit directly: the middleware measures the whole body, framing included, so a
    cap set to the bare file limit rejects a legal file of exactly that size depending on
    how many boundary bytes the client sent.

    An outer bound for the edge, not a replacement for the service's own check on the
    extracted file — that check is what a caller is told it exceeded.
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

    Middleware rather than a check inside the handler, because a framework resolves a
    multipart form by reading the whole body first: ``await request.form()`` runs before
    the endpoint's dependencies.

    The cap covers the whole body, framing included (see ``body_cap_for_upload``), which
    makes it a coarse outer bound rather than a replacement for the service's own check
    on the extracted file.

    Args:
        max_bytes: Largest request body accepted, in bytes.
        reported_limit: The limit to put in the error's ``details.limit``. Pass the
            service's own file-size limit so both gates advertise one number — a caller
            told to trim to the transport cap lands just above the service's check and is
            refused a second time. Defaults to ``max_bytes``, correct for a service that
            caps a body it does not otherwise check.
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
            # `declared` measures the whole body, `reported_limit` the file: an upper
            # bound on what the caller sent, not an exact measurement of it.
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
