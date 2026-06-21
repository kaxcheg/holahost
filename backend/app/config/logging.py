from __future__ import annotations

import logging
import re

from pydantic import SecretStr
from pythonjsonlogger.json import JsonFormatter

_LOGGER_NAME = "holahost"
_logger = logging.getLogger(_LOGGER_NAME)

# §10.5 — fixed allowlist for ``log_event`` **field names (keyword args)**. ``event`` / ``timestamp``
# / ``level`` are injected by the helper/formatter and are intentionally NOT in this set.
_ALLOWED_LOG_FIELDS = frozenset(
    {
        "request_id",
        "endpoint",
        "method",
        "status",
        "duration_ms",
        "ip_hash",
        "lead_id",
        "guidebook_id",
        "error_code",
        "error_message_sanitized",
        "sample_tokens_used",
        "deleted_guidebooks",
        "expired_magic_links",
        "deleted_rate_windows",
    }
)

# §10.5 value-filter (override): the allowlist guards field NAMES; this guards field VALUES as a
# defense-in-depth backup. Values are REDACTED (never asserted-on — a logging helper must not add a
# prod-crash path inside an error-logging flow). ``error_message_sanitized`` is the only free-text
# field, so the email / opaque-token regex scrub is scoped to it (UUID ids are 36 chars → unmatched
# by ``{40,}``).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{40,}")


def configure_logging(level: int = logging.INFO) -> None:
    """Install the structured-JSON formatter on the ``holahost`` logger (spec §10.5)."""
    handler = logging.StreamHandler()
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


def _redact_value(key: str, value: object) -> object:
    """Redact one log field value (SecretStr → ``"<redacted>"``; sanitize the message field)."""
    if isinstance(value, SecretStr):
        return "<redacted>"
    if key == "error_message_sanitized" and isinstance(value, str):
        return _TOKEN_RE.sub("<token>", _EMAIL_RE.sub("<email>", value))
    return value


def log_event(event_name: str, *, level: int = logging.INFO, **fields: object) -> None:
    """Emit one structured JSON log event with an allowlisted field set (spec §10.5).

    Args:
        event_name: Event identifier; emitted as the ``event`` field.
        level: Severity for this record (``logging.INFO`` / ``WARNING`` / ``ERROR`` …). The CALL
            SITE chooses it — the helper never infers severity. Defaults to ``logging.INFO`` (the
            common telemetry case in §10.5); pass ``logging.ERROR`` for failure events so the
            CloudWatch ``error_count`` metric filter (``level=ERROR``) matches.
        **fields: Structured fields; every key MUST be in :data:`_ALLOWED_LOG_FIELDS`. Each VALUE
            passes through :func:`_redact_value` (SecretStr → ``"<redacted>"``;
            ``error_message_sanitized`` regex-scrubbed) as a PII/secret backup.

    :raises AssertionError: if any field NAME is outside the allowlist (§10.5 — assert retained in
        production; not gated on ``__debug__``). Field VALUES are redacted, never asserted on.
    """
    disallowed = set(fields) - _ALLOWED_LOG_FIELDS
    assert not disallowed, f"log_event: disallowed fields {sorted(disallowed)}"  # noqa: S101 (§10.5)
    safe = {key: _redact_value(key, value) for key, value in fields.items()}
    _logger.log(level, event_name, extra={"event": event_name, **safe})
