"""The completion event for a request refused before it reached a route.

Middleware answers without ever entering a handler, so nothing downstream would log
these — and they are exactly the outcomes a service's metric filters count
(``RateLimitExceededError``, ``401``, the transport ``413``). The shape is the platform's,
so it lives here rather than being written out again in each service.
"""

from __future__ import annotations

import logging
import time

from holahost_observability import OP_COMPLETED, log_event
from starlette.types import Scope


def log_rejection(scope: Scope, *, outcome: str, detail: str | None = None) -> None:
    """The ``on_rejected`` callback every middleware in this package accepts.

    Reads what earlier middleware left in ``scope["state"]``: the request id and the timer
    are always there (``RequestIdMiddleware`` is outermost), the token only once
    authentication has succeeded — which is why an auth failure logs no ``client_id``.

    Nothing about the event is service-specific — the field allowlist is process state
    ``configure_logging`` sets — so the logger is imported here rather than passed in.
    """
    state = scope.get("state", {})
    start = state.get("start_time")
    token = state.get("token")
    log_event(
        OP_COMPLETED,
        # WARNING, flat: every outcome this can be handed — a missing header, bad
        # credentials, an over-quota caller, an over-sized body — is the caller's doing and
        # none reaches 5xx.
        level=logging.WARNING,
        route=f"{scope['method']} {scope['path']}",
        outcome=outcome,
        duration_ms=(time.monotonic() - start) * 1000 if start is not None else 0.0,
        request_id=state.get("request_id"),
        client_id=getattr(token, "client_id", None),
        sub=getattr(token, "subject", None),
        # Server-side only. Passed raw — the scrubber runs at the sink.
        error_reason=detail,
    )
