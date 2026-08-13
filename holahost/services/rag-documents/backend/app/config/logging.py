from __future__ import annotations

import logging
import re
import sys

from pythonjsonlogger.json import JsonFormatter

_LOGGER_NAME = "holahost"
_logger = logging.getLogger(_LOGGER_NAME)

# US-R11 — fixed allowlist for `log_event` field NAMES. `event`/`timestamp`/`level` are
# injected by the formatter and intentionally excluded from this set.
_ALLOWED_LOG_FIELDS = frozenset(
    {
        "request_id",
        "client_id",
        "sub",
        "document_id",
        "route",
        "outcome",
        "duration_ms",
        "error_code",
        "error_message_sanitized",
        "chunk_count",
        "hits",
        "top_score",
        "stage_ms",
    }
)

# Value-filter (defense-in-depth backup to the name allowlist): scrub tokens/emails out
# of the one free-text field. UUID ids are 36 chars, so `{40,}` never matches them.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_=-]{40,}")


def configure_logging(level: int = logging.INFO) -> None:
    """Install the structured-JSON formatter on the `holahost` logger (US-R11/§3.4).

    Writes to stdout explicitly — `logging.StreamHandler()` with no argument defaults
    to stderr, which §3.4's tech-stack table ("structured JSON в stdout") doesn't ask
    for; the container's log driver is expected to collect stdout.
    """
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
    """Return a module logger namespaced under the configured `holahost` logger."""
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")


def _redact_value(key: str, value: object) -> object:
    if key == "error_message_sanitized" and isinstance(value, str):
        return _TOKEN_RE.sub("<token>", _EMAIL_RE.sub("<email>", value))
    return value


def log_event(event_name: str, *, level: int = logging.INFO, **fields: object) -> None:
    """Emit one structured JSON log event with an allowlisted field set (US-R11).

    :raises AssertionError: any field NAME is outside `_ALLOWED_LOG_FIELDS` — retained
        in production (not gated on `__debug__`); document/chunk/query text and token
        bodies must never even reach this call, and this is the last line of defense.
    """
    disallowed = set(fields) - _ALLOWED_LOG_FIELDS
    assert not disallowed, f"log_event: disallowed fields {sorted(disallowed)}"  # noqa: S101
    safe = {key: _redact_value(key, value) for key, value in fields.items()}
    _logger.log(level, event_name, extra={"event": event_name, **safe})
