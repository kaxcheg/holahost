"""HTTP response envelope for the Lambda interface (spec §10.3 / §10.5 / §10.8).

Single source of truth for the error ``code`` → HTTP-status map and the error/success envelope,
plus the API security headers and CORS. The handler imports this module as ``to_http_response`` and
calls :func:`ok` / :func:`from_application_error` / :func:`internal` / :func:`preflight` (C-16).
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import TYPE_CHECKING, TypedDict

from application.exceptions import ApplicationError

if TYPE_CHECKING:
    from config.config import Settings


class InternalDetails(TypedDict):
    """``details`` for ``ERR_INTERNAL`` (§10.8).

    ``ERR_INTERNAL`` has no dedicated ``ApplicationError`` subclass (it is the base default ``code``,
    emitted by :func:`internal`), so its ``details`` schema is sourced from this ``TypedDict`` — the
    single source the OpenAPI exporter derives the ``ERR_INTERNAL`` variant from (§11.3).
    """

    request_id: str


# code → HTTP status (§10.8). The interface layer owns this mapping (no executable map in the
# application layer); it is the source of truth for code ↔ status.
HTTP_STATUS_BY_CODE: dict[str, int] = {
    "ERR_INVALID_API_KEY": 401,
    "ERR_INVALID_MAGIC_LINK": 401,
    "ERR_NOT_FOUND": 404,
    "ERR_NO_GUIDEBOOK": 409,
    "ERR_EMAIL_CONFLICT": 409,
    "ERR_PAYLOAD_TOO_LARGE": 413,
    "ERR_TOO_MANY_CHUNKS": 413,
    "ERR_UNSUPPORTED_MEDIA_TYPE": 415,
    "ERR_EMPTY_DOCUMENT": 422,
    "ERR_INVALID_PAYLOAD": 422,
    "ERR_RATE_LIMIT": 429,
    "ERR_SAMPLE_BUDGET_EXHAUSTED": 429,
    "ERR_UPSTREAM_LLM": 502,
    "ERR_UPSTREAM_EMAIL": 502,
    "ERR_INTERNAL": 500,
}

# §10.5 defense-in-depth: scrub email / opaque tokens from the user-facing ``message``.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{40,}")

# §10.3 API security headers (Lambda Function URL responses contain secrets/PII).
_API_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


def _sanitize(message: str) -> str:
    """Scrub email / opaque-token PII from a user-facing error message (§10.5 / §10.8)."""
    return _TOKEN_RE.sub("<token>", _EMAIL_RE.sub("<email>", message))


def _cors_headers(settings: Settings) -> dict[str, str]:
    """CORS headers (§10.3). The allowed origin is purely the configured ``frontend_origin`` — no
    env-branching; dev sets it to the local Vite dev server (e.g. ``http://localhost:5173``) via env.
    """
    return {
        "Access-Control-Allow-Origin": settings.frontend_origin,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Api-Key, X-Magic-Link",
        "Access-Control-Allow-Credentials": "false",
        "Access-Control-Max-Age": "86400",
    }


def _headers(settings: Settings) -> dict[str, str]:
    return {"Content-Type": "application/json", **_API_SECURITY_HEADERS, **_cors_headers(settings)}


def _response(status: int, body: dict[str, object], settings: Settings) -> dict[str, object]:
    return {
        "statusCode": status,
        "headers": _headers(settings),
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


def to_response(err: ApplicationError) -> tuple[int, dict[str, object]]:
    """Map an ``ApplicationError`` to ``(HTTP status, envelope dict)`` (§10.8).

    Args:
        err: The application error (its ``code`` must be in :data:`HTTP_STATUS_BY_CODE`).

    Returns:
        ``(status, {"error": {"code", "message", "details"}})``; ``message`` is PII-sanitized.
    """
    body: dict[str, object] = {
        "error": {
            "code": err.code,
            "message": _sanitize(str(err)),
            "details": err.details_dict(),
        }
    }
    return HTTP_STATUS_BY_CODE[err.code], body


def ok(result: object, settings: Settings) -> dict[str, object]:
    """Build a 200 response. ``None`` → ``{"status": "sent"}``; a Result dataclass → its fields.

    :raises TypeError: if ``result`` is neither ``None`` nor a dataclass instance.
    """
    if result is None:
        body: dict[str, object] = {"status": "sent"}
    elif dataclasses.is_dataclass(result) and not isinstance(result, type):
        body = dataclasses.asdict(result)
    else:
        raise TypeError(f"cannot serialize result of type {type(result)!r}")
    return _response(200, body, settings)


def from_application_error(err: ApplicationError, settings: Settings) -> dict[str, object]:
    """Map an ``ApplicationError`` to a full Lambda HTTP response (status + envelope + headers)."""
    status, body = to_response(err)
    return _response(status, body, settings)


def internal(request_id: str, settings: Settings) -> dict[str, object]:
    """Build the 500 ``ERR_INTERNAL`` response carrying ``request_id`` for correlation (§10.8)."""
    details: InternalDetails = {"request_id": request_id}
    body: dict[str, object] = {
        "error": {
            "code": "ERR_INTERNAL",
            "message": "Internal server error",
            "details": details,
        }
    }
    return _response(500, body, settings)


def preflight(settings: Settings) -> dict[str, object]:
    """Build the CORS preflight (OPTIONS) response (§10.3)."""
    return {"statusCode": 204, "headers": _headers(settings), "body": "", "isBase64Encoded": False}
