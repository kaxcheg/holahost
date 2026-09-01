"""Structured JSON logging every Holahost service shares.

The mechanism is the platform's; the vocabulary is half the platform's and half the
service's. ``CORE_LOG_FIELDS`` are the fields every service emits and every log-derived
metric filter reads, so they are fixed here. Everything a service logs beyond them is its
own, declared once where it calls :func:`configure_logging`.

Nothing in this module inspects content. The protection against document text, prompt
text or a token body reaching a log line is structural — a field *name* outside the
allowlist raises. The one exception is ``error_reason``, the single free-text field, whose
value is scrubbed at the sink by :func:`_redact_value`.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Collection

from pythonjsonlogger.json import JsonFormatter

_LOGGER_NAME = "holahost"
_logger = logging.getLogger(_LOGGER_NAME)

OP_COMPLETED = "op_completed"
"""The platform's operation-completion event (one per request, success or failure).

One name across every service, because the CloudWatch metric filters for 5xx, auth
failures, rate-limit refusals, success rate and p95 duration are derived from it: a
per-service name would make one set of filters into N copies of it.
"""

STARTUP_COMPLETED = "startup_completed"
"""Emitted once per process, after the composition root has finished building the app."""

CORE_LOG_FIELDS = frozenset(
    {
        "request_id",
        "client_id",
        "sub",
        "route",
        "outcome",
        "duration_ms",
        # No `error_code`: `outcome` carries the failure's identity, and it is what the
        # metric filters match on.
        "error_reason",
    }
)
"""Fields every service emits on ``op_completed``. Metric filters read only these."""


class DisallowedLogFieldError(RuntimeError):
    """A ``log_event`` call passed a field name outside its allowlist.

    A defect in the calling code, not a runtime condition: emitting the line minus the
    offending field would leave it in place and invisible.
    """


# Value filter, a backup to the name allowlist for the one free-text field. UUIDs are 36
# characters, so `{40,}` never matches one.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_=-]{40,}")


_allowed_fields: frozenset[str] = CORE_LOG_FIELDS
"""What :func:`log_event` accepts, set by :func:`configure_logging`.

Module state, like the logger it sits beside. Before configuration it is the platform core
alone, so a service field logged too early raises rather than slipping through.
"""


def configure_logging(level: int = logging.INFO, *, extra_fields: Collection[str] = ()) -> None:
    """Install the structured-JSON formatter, and declare what may be logged.

    Called once, by the composition root, before anything logs.

    Writes to stdout explicitly: ``StreamHandler()`` with no argument defaults to stderr,
    and the container's log driver collects stdout.

    Args:
        level: Threshold for the ``holahost`` logger.
        extra_fields: Field names this service emits beyond the platform's core set.
            ``event``, ``timestamp`` and ``level`` are injected by the formatter and are
            not declared here.
    """
    global _allowed_fields
    _allowed_fields = CORE_LOG_FIELDS | frozenset(extra_fields)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )
    _logger.handlers.clear()
    _logger.addHandler(handler)
    _logger.setLevel(level)
    _logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Return a module logger namespaced under the configured ``holahost`` logger."""
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


def _redact_value(key: str, value: object) -> object:
    """Scrub tokens and e-mail addresses out of the one free-text field.

    Callers pass their reason raw; the scrubbing happens here, the one place that sees
    every event. Not applied to the other fields: ``request_id`` comes verbatim from a
    caller-supplied header, and a 64-character trace id matches ``_TOKEN_RE`` exactly, so
    scrubbing every string would replace the correlation key with ``<token>``.
    """
    if key == "error_reason" and isinstance(value, str):
        return _TOKEN_RE.sub("<token>", _EMAIL_RE.sub("<email>", value))
    return value


def log_event(event_name: str, *, level: int = logging.INFO, **fields: object) -> None:
    """Emit one structured JSON event.

    A module function rather than something a service builds and passes around: the
    libraries that write this event (the HTTP edge's rejection log, its exception handlers)
    would otherwise take a logger as a parameter.

    Raises:
        DisallowedLogFieldError: a field name is outside the allowlist.
    """
    # A `raise`, not an `assert`: `PYTHONOPTIMIZE` compiles asserts away, which would make
    # the allowlist a silent no-op wherever the flag is set.
    disallowed = set(fields) - _allowed_fields
    if disallowed:
        raise DisallowedLogFieldError(f"log_event: disallowed fields {sorted(disallowed)}")
    safe = {key: _redact_value(key, value) for key, value in fields.items()}
    _logger.log(level, event_name, extra={"event": event_name, **safe})
