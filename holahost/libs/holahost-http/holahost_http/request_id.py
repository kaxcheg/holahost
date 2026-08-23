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
    attaches it — the platform gateway on staging and prod, the calling tool on dev, where
    there is no gateway — so its absence means a caller is misconfigured or is reaching the
    service by a path it was not meant to. Letting that through records the fact as a
    silent null in the log and forfeits end-to-end tracing with no distinct signal that it
    happened.

    Requiring it is one parameter rather than a second middleware on purpose. The two
    cannot be composed independently: the enforcing half reads what the observing half
    writes, so mounted in the wrong order it finds an empty state and answers *every*
    request — the correctly-formed ones included — with a rejection. That is a total
    outage produced by a wiring order nothing checks. One class makes the order
    unexpressible.

    The rule is the platform's; the answer is the service's. This library owns no code for
    "malformed request", having no taxonomy to draw one from, so a service passes its own.

    Plain ASGI rather than ``BaseHTTPMiddleware``: this is the outermost middleware, so
    everything else — notably a body-size limiter's byte counting — receives the request
    through it. ``BaseHTTPMiddleware`` re-plumbs the request body through anyio memory
    streams to offer its ``Request``/``Response`` convenience, which is real machinery to
    run on every byte of every upload in exchange for reading one header.

    Args:
        missing_header_error: What to answer with when the header is absent. ``None``
            (default) observes without ever rejecting. Consider an error carrying no
            ``details``: this refusal happens before authentication, so naming the header
            in the body tells a caller who arrived by an unintended path exactly what to
            add to get past it. ``on_rejected`` is told which header was missing either
            way.
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
        for raw_name, raw_value in scope["headers"]:
            if raw_name.lower() == REQUEST_ID_HEADER.encode():
                request_id = raw_value.decode("latin-1")
                break

        state = scope.setdefault("state", {})
        state["start_time"] = time.monotonic()
        state["request_id"] = request_id

        if request_id is None:
            error = self._missing_header_error
            if error is not None and scope["path"] not in self._exempt_paths:
                if self._on_rejected is not None:
                    # Which header was missing goes to the log, not necessarily to the
                    # caller: this rejection happens before authentication, so a service
                    # may well choose to answer it mute (see `missing_header_error`).
                    self._on_rejected(
                        scope, outcome=error.code, detail=f"missing {REQUEST_ID_HEADER}"
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
