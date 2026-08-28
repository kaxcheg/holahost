"""``X-Request-ID`` propagation, the per-request timer, and the header's requirement."""

from __future__ import annotations

import time
from collections.abc import Sequence

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from holahost_http.errors import PlatformError, RejectionLogger, send_platform_error

REQUEST_ID_HEADER = "x-request-id"


class RequestIdMiddleware:
    """Records ``X-Request-ID`` (or its absence), starts the request timer, echoes it back.

    Writes into ``scope["state"]``, which is what ``request.state`` reads, so handlers and
    exception handlers see ``request.state.request_id`` / ``.start_time`` as usual. Never
    synthesizes a missing header — it only reports what actually arrived.

    Pass ``missing_header_error`` to also *require* the header. Every real entry path
    attaches it — the platform gateway on staging and prod, the calling tool on dev — so
    its absence means a caller is misconfigured or reaching the service by a path it was
    not meant to. A header that arrives blank (empty or whitespace) is treated as absent,
    here and in ``scope["state"]``: it carries no correlation key, so honouring it would
    satisfy the requirement while defeating its purpose.

    Requiring it is one parameter rather than a second middleware because the two cannot
    be composed independently: the enforcing half reads what the observing half writes, so
    in the wrong order it finds an empty state and rejects *every* request. One class
    makes that order unexpressible. The rule is the platform's, the answer is the
    service's — this library has no taxonomy to draw a "malformed request" error from, so
    a service passes its own.

    Plain ASGI rather than ``BaseHTTPMiddleware``: this is the outermost middleware, so
    every byte of every upload passes through it, and ``BaseHTTPMiddleware`` would re-plumb
    the body through anyio memory streams in exchange for reading one header.

    Args:
        missing_header_error: What to answer with when the header is absent or blank.
            ``None`` (default) observes without ever rejecting. Consider an error carrying
            no ``details``: this refusal happens before authentication, so naming the
            header in the body tells a caller who arrived by an unintended path exactly
            what to add to get past it. ``on_rejected`` is told which header it was, and
            whether it was missing or blank, either way.
        status: HTTP status for that error.
        exempt_paths: Exact paths served without the header — health checks, which probes
            do not attach tracing headers to. Exempts them from the *requirement* only;
            the header is still recorded and echoed if one arrives.
        on_rejected: Optional callback used to log a rejection.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        missing_header_error: PlatformError | None = None,
        status: int = 422,
        exempt_paths: Sequence[str] = (),
        on_rejected: RejectionLogger | None = None,
    ) -> None:
        self.app = app
        self._missing_header_error = missing_header_error
        self._status = status
        self._exempt_paths = frozenset(exempt_paths)
        self._on_rejected = on_rejected

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id: str | None = None
        header_arrived = False
        for raw_name, raw_value in scope["headers"]:
            if raw_name.lower() == REQUEST_ID_HEADER.encode():
                header_arrived = True
                # Blank counts as absent: a presence check that `X-Request-ID:` with
                # nothing after it satisfies would leave `""` as the correlation key.
                request_id = raw_value.decode("latin-1").strip() or None
                break

        state = scope.setdefault("state", {})
        state["start_time"] = time.monotonic()
        state["request_id"] = request_id

        if request_id is None:
            error = self._missing_header_error
            if error is not None and scope["path"] not in self._exempt_paths:
                if self._on_rejected is not None:
                    # The cause goes to the log, not necessarily to the caller: this
                    # rejection precedes authentication, so a service may answer it mute.
                    # Blank and missing point at different faults — a proxy filling the
                    # header from an unset variable, versus a caller without one.
                    reason = "blank" if header_arrived else "missing"
                    self._on_rejected(
                        scope, outcome=error.code, detail=f"{reason} {REQUEST_ID_HEADER}"
                    )
                await send_platform_error(scope, receive, send, status=self._status, error=error)
                return
            await self.app(scope, receive, send)
            return

        # Bound to its own name before the closure: mypy widens a captured variable back
        # to its declared type (`str | None`), discarding the narrowing above.
        echoed = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = echoed
            await send(message)

        await self.app(scope, receive, send_with_request_id)
