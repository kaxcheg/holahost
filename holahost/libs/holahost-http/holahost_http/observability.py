"""The completion event: for a request refused before it reached a route, and for one that
reached it — with the fields the route attached along the way.

Middleware answers without ever entering a handler, so nothing downstream would log
these — and they are exactly the outcomes a service's metric filters count
(``RateLimitExceededError``, ``401``, the transport ``413``). The shape is the platform's,
so it lives here rather than being written out again in each service.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

from holahost_observability import CORE_LOG_FIELDS, OP_COMPLETED, log_event
from starlette.requests import Request
from starlette.types import Scope

_LOG_FIELDS = "log_fields"


def add_log_fields(request: Request, **fields: object) -> None:
    """Attach fields to this request's completion event, whichever handler ends up writing it.

    For what a route knows before its use case runs — the model a caller asked for — and an
    error raised from inside the use case would otherwise take out of the event: the exception
    handlers merge these into the line they write. The names have to be in the service's
    log-field allowlist.

    Raises:
        ValueError: a name is one of the platform's core fields, which only the platform writes.
    """
    core = sorted(CORE_LOG_FIELDS.intersection(fields))
    if core:
        raise ValueError(f"add_log_fields: {core} are core fields of the completion event")
    current: dict[str, object] = getattr(request.state, _LOG_FIELDS, {})
    setattr(request.state, _LOG_FIELDS, {**current, **fields})


def request_log_fields(request: Request) -> Mapping[str, object]:
    """What the route attached with ``add_log_fields``; empty when it attached nothing."""
    fields: Mapping[str, object] = getattr(request.state, _LOG_FIELDS, {})
    return fields


def log_completion(
    request: Request,
    *,
    outcome: str,
    level: int = logging.INFO,
    error_reason: str | None = None,
    fields: Mapping[str, object] | None = None,
) -> None:
    """Write the completion event of a request that reached a route — its success or a refusal.

    The core is assembled here, the same way for every line, so a filter on ``route`` counts the
    successes a route writes and the refusals its exception handlers write alike. The service's
    own fields are what the route attached (``add_log_fields``) and ``fields``, the latter winning
    on a clash. A service field named like a core one is dropped rather than allowed to fail the
    call: in an exception handler that failure would turn the answer into a traceback.
    """
    token = getattr(request.state, "token", None)
    start = getattr(request.state, "start_time", None)
    # `Any`, not `object`: splatting `object` values past `log_event`'s `level: int` does not
    # type-check.
    service: dict[str, Any] = {
        name: value
        for name, value in {**request_log_fields(request), **(fields or {})}.items()
        if name not in CORE_LOG_FIELDS
    }
    log_event(
        OP_COMPLETED,
        level=level,
        route=f"{request.method} {request.url.path}",
        outcome=outcome,
        duration_ms=(time.monotonic() - start) * 1000 if start is not None else 0.0,
        request_id=getattr(request.state, "request_id", None),
        client_id=getattr(token, "client_id", None),
        sub=getattr(token, "subject", None),
        # Server-side only. Passed raw — the scrubber runs at the sink.
        error_reason=error_reason,
        **service,
    )


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
