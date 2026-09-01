"""This service's half of the platform logging contract.

The logger, the allowlist mechanism, the scrubber and the core field set live in
`holahost-observability`. What is this service's own is the list below: the fields it emits
on `op_completed` beyond the platform's core seven.

`log_event` is re-exported so the rest of the service keeps importing it from one place,
but it is the library's own function: the allowlist it enforces is process state that
`configure_logging` sets, not something bound into a callable and passed around. That is
what lets the platform's own writers — the edge's rejection log, its exception handlers —
emit without a service handing them anything.
"""

from __future__ import annotations

import logging

from holahost_observability import DisallowedLogFieldError, log_event
from holahost_observability import configure_logging as _configure_logging

SERVICE_LOG_FIELDS: frozenset[str] = frozenset()
"""Fields only this service emits. The platform's own (`request_id`, `client_id`, `sub`,
`route`, `outcome`, `duration_ms`, `error_reason`) come from `CORE_LOG_FIELDS` and are not
repeated here.

Add a field only when something reads it — a metric filter, a dashboard, an operator
answering a specific question. Never document text, prompt text, a query or a token body:
the allowlist is what makes that structurally impossible."""


def configure_logging(level: int = logging.INFO) -> None:
    """Install the platform logger and declare this service's own fields.

    Called once by `scripts/bootstrap.py`, before anything logs. Until it runs, only the
    platform's core fields are accepted — a service field logged too early raises rather
    than slipping through, which is the safe direction.
    """
    _configure_logging(level, extra_fields=SERVICE_LOG_FIELDS)


__all__ = ["SERVICE_LOG_FIELDS", "DisallowedLogFieldError", "configure_logging", "log_event"]
