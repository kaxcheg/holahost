from __future__ import annotations

import logging
import re
import sys

from pythonjsonlogger.json import JsonFormatter

_LOGGER_NAME = "holahost"
_logger = logging.getLogger(_LOGGER_NAME)


class DisallowedLogFieldError(RuntimeError):
    """A `log_event` call passed a field name outside `_ALLOWED_LOG_FIELDS` (US-R11).

    A defect in the calling code, not a runtime condition — which is why it is raised
    rather than dropped or logged: the allowlist exists so that document text, chunk
    text, query text and token bodies cannot reach a log line, and silently emitting the
    line minus the offending field would leave the defect in place and invisible.
    """


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
        # No `error_code`: `outcome` already carries the failure's code (§8.7 lists it as
        # the field every failure metric matches on), and every caller that ever set
        # `error_code` set it to the same value it passed as `outcome`.
        "error_reason",
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
    """Scrub tokens and e-mail addresses out of the one free-text field.

    **This is what does the sanitising**, and the field is named for what it holds rather
    than for that: callers pass their reason raw (`errors._log_failure` passes `str(exc)`,
    `edge.log_rejection` the middleware's own reason), and the scrubbing happens here, at
    the sink — the only place that sees every event. It was `error_message_sanitized`,
    which named the processing and named it from the wrong side: it read as a
    precondition on the caller, and no caller ever met it.

    The field name is hardcoded rather than looked up in a set of free-text fields:
    there is exactly one, and a set of one generalises nothing. A second would mean
    editing this function, which is where the reasoning below lives anyway.

    Not applied to the other fields, and that is a decision rather than an optimisation.
    `request_id` is taken verbatim from a caller-supplied header with no length cap, and
    `sub`/`client_id` are opaque identifiers — a 64-character trace id matches
    `_TOKEN_RE` exactly, so scrubbing every string would replace the correlation key with
    `<token>` and cost more than it protects. Those fields are not free text; the name
    allowlist is what vouches for them.
    """
    if key == "error_reason" and isinstance(value, str):
        return _TOKEN_RE.sub("<token>", _EMAIL_RE.sub("<email>", value))
    return value


def log_event(event_name: str, *, level: int = logging.INFO, **fields: object) -> None:
    """Emit one structured JSON log event with an allowlisted field set (US-R11).

    Division of responsibility: the caller passes its reason raw and must never pass
    document, chunk or query text at all — enforced structurally, by the field NAME
    allowlist (nothing here inspects content). Scrubbing tokens and addresses out of the
    one free-text field is this function's job, through `_redact_value`.

    :raises DisallowedLogFieldError: any field NAME is outside `_ALLOWED_LOG_FIELDS`.

    A real `raise`, not an `assert`. `python -O` / `PYTHONOPTIMIZE=1` compiles an
    `assert` away entirely, so the check that stood here was absent from exactly the
    kind of deployment most likely to enable it — while its own docstring claimed it was
    "retained in production". Nothing pins `PYTHONOPTIMIZE` in the image, so an operator
    adding it as a routine optimisation turned US-R11's enforced allowlist into a no-op,
    with no signal. `holahost_auth.dependency` avoids an `assert` for the same reason.
    """
    disallowed = set(fields) - _ALLOWED_LOG_FIELDS
    if disallowed:
        raise DisallowedLogFieldError(f"log_event: disallowed fields {sorted(disallowed)}")
    safe = {key: _redact_value(key, value) for key, value in fields.items()}
    _logger.log(level, event_name, extra={"event": event_name, **safe})
