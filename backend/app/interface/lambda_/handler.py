"""AWS Lambda entry point: dispatch → execute → envelope, with per-request logging (spec §8.5).

``handle`` is the fully testable core (takes an injected ``container``); the thin ``lambda_handler``
wrapper binding the real cold-start ``container`` is added once ``scripts.bootstrap`` exists (T5).
Error handling order (§8.5): ``ApplicationError`` → mapped HTTP; any other ``Exception`` →
``logger.exception`` + 500 ``ERR_INTERNAL`` (no stack trace in the body).
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

from application.exceptions import ApplicationError
from config.logging import get_logger, log_event
from interface.lambda_ import response_envelope as to_http_response
from interface.lambda_.router import dispatch

logger = get_logger(__name__)


def handle(event: dict[str, Any], context: Any, container: Any) -> dict[str, object]:
    """Process one Function URL event end-to-end and return the Lambda HTTP response."""
    request_id = getattr(context, "aws_request_id", None) or str(uuid4())
    settings = container.settings
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "")
    if method == "OPTIONS":
        return to_http_response.preflight(settings)
    start = time.monotonic()
    try:
        cmd, use_case = dispatch(event, container)
        result = use_case.execute(cmd)
        resp = to_http_response.ok(result, settings)
        _log(request_id, path, method, resp["statusCode"], start, getattr(cmd, "ip_hash", None))
        return resp
    except ApplicationError as exc:
        resp = to_http_response.from_application_error(exc, settings)
        _log(request_id, path, method, resp["statusCode"], start, None, error_code=exc.code)
        return resp
    except Exception:
        logger.exception("unhandled error in lambda_handler")
        resp = to_http_response.internal(request_id, settings)
        _log(request_id, path, method, 500, start, None, error_code="ERR_INTERNAL")
        return resp


def _log(
    request_id: str,
    endpoint: str,
    method: str,
    status: object,
    start: float,
    ip_hash: str | None,
    *,
    error_code: str | None = None,
) -> None:
    """Emit the ``http_request_completed`` event with allowlisted fields only (§10.5)."""
    fields: dict[str, object] = {
        "request_id": request_id,
        "endpoint": endpoint,
        "method": method,
        "status": status,
        "duration_ms": int((time.monotonic() - start) * 1000),
    }
    if ip_hash is not None:
        fields["ip_hash"] = ip_hash
    if error_code is not None:
        fields["error_code"] = error_code
    level = logging.ERROR if (isinstance(status, int) and status >= 500) else logging.INFO
    log_event("http_request_completed", level=level, **fields)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, object]:
    """AWS Lambda entry point. Binds the cold-start ``container`` (lazy import avoids building it on
    module import, so tests can import :func:`handle` without triggering the real DI graph)."""
    from scripts.bootstrap import container

    return handle(event, context, container)
