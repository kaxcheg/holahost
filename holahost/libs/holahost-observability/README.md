# holahost-observability

Structured JSON logging shared by Holahost services: the logger, the field allowlist that
keeps content out of it, and the platform's operation-completion event.

Consumed as a [path dependency](../../README.md#shared-libraries).

## Why a library, and why this one has no HTTP dependency

Every service is required to log in JSON with an allowlisted field set, and every service
derives its CloudWatch metrics — 5xx rate, auth failures, rate-limit refusals, success
rate, p95 duration — from one event with fixed field names. Both halves have to be the
same everywhere or the metric filters stop being one thing and become N copies of it.

The logger is deliberately not part of `holahost-http`. It is called from places that have
no ASGI application at all: a composition root before the app is built, `alembic`'s
`env.py`, a one-off role-provisioning script, and eventually a queue worker. Writing a log
line from a migration should not cost a web stack, so the only runtime dependency here is
`python-json-logger`.

## Usage

The allowlist is split: `CORE_LOG_FIELDS` belongs to the platform and is fixed; anything
else a service logs is its own and is declared once, in the call to `configure_logging`.

```python
# app/config/logging.py
from holahost_observability import configure_logging as _configure_logging

SERVICE_LOG_FIELDS = frozenset({"document_id", "chunk_count"})


def configure_logging(level: int = logging.INFO) -> None:
    _configure_logging(level, extra_fields=SERVICE_LOG_FIELDS)
```

```python
# anywhere in the service, or in any Holahost library
from holahost_observability import OP_COMPLETED, log_event

log_event(OP_COMPLETED, route="POST /documents", outcome="success", duration_ms=41.2)
```

`configure_logging()` installs the JSON formatter on the `holahost` logger *and* sets the
allowlist. It is called once, by the composition root, before anything logs.

`log_event` is a module function reading that process state, not a bound callable a service
passes around: the alternative makes the logger a parameter of every library that writes the
platform's own events (the HTTP edge's rejection log, its exception handlers). Process-wide
state is what logging already is — the allowlist sits beside the logger and its handler.

Before `configure_logging` runs the allowlist is the platform core alone, so a service field
logged too early **raises**; the inverse — a field allowed because some step has not run —
cannot happen.

## The contract a service inherits

- **Event name.** `OP_COMPLETED` — one per request, success or failure. `STARTUP_COMPLETED`
  — once per process.
- **Core fields.** `request_id`, `client_id`, `sub`, `route`, `outcome`, `duration_ms`,
  `error_reason`. The failure's identity is `outcome`, not a separate field: that is what
  the metric filters match on.
- **Level.** `ERROR` on 5xx, `WARNING` on any refusal caused by the caller, `INFO` on
  success and on startup. Filters match `$.outcome` and never read the level — it exists
  for a person reading the log.
- **Content never reaches a log line.** Enforced by field *name*: a name outside the
  allowlist raises `DisallowedLogFieldError` rather than being dropped, because a silently
  shortened line leaves the defect in place and invisible. The one free-text field,
  `error_reason`, is additionally scrubbed of tokens and e-mail addresses at the sink —
  callers pass their reason raw.
