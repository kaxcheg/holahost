"""Everything the shared middleware needs to know about *this* service (§3.1, §8.1).

`holahost-http` and `holahost-auth` supply the mechanisms — request-id propagation, a
body-size cap, authentication, a rate limiter — deliberately without opinions about which
routes they apply to, how big is too big, what a rejection is called on the wire, or how
it is logged. Those are this service's contract (§3.8, §7.6, §8.1, §8.7), and they all
live here: one module for the values and rules the edge is parameterised with, so
`app.py` is left holding nothing but the wiring.

`api_base.py` stays separate and minimal: the container healthcheck imports it directly,
so it must not drag in the application layer to answer "what is my base path".
"""

from __future__ import annotations

import logging
import time

from holahost_http import body_cap_for_upload
from starlette.types import Scope

from application.exceptions import MalformedRequestError
from application.limits import MAX_UPLOAD_SIZE
from config.logging import log_event
from interface.http.api_base import API_BASE_URL

_DOCUMENTS_PREFIX = f"{API_BASE_URL}/documents"
HEALTH_PATH = f"{API_BASE_URL}/health"

# Shared vocabulary: `bucket_for` maps a request to a bucket, `dependencies.
# get_rate_limiter` maps a bucket to a ceiling. Naming them in either place would only
# pick which one imports the other.
INGEST_BUCKET = "ingest"
READ_BUCKET = "read"

# The unit every RATE_LIMIT_* setting is counted in (§3.7). A constant rather than a
# setting: the window is what those numbers *mean*, and halving it would silently halve
# every ceiling while the .env files went on claiming 60 and 600.
RATE_LIMIT_WINDOW_SECONDS = 3600

# A transport limit: it bounds the whole HTTP body, multipart framing included, and only
# decides how much the edge reads before anyone can look. `MAX_UPLOAD_SIZE` stays the
# application's own check on the extracted file (§3.8). Derived so the two cannot drift.
MAX_REQUEST_BODY_SIZE = body_cap_for_upload(MAX_UPLOAD_SIZE)

REPORTED_UPLOAD_LIMIT = MAX_UPLOAD_SIZE
"""The `limit` a 413 from either size gate advertises (§7.6, US-R01).

The middleware enforces `MAX_REQUEST_BODY_SIZE`, `CreateDocumentUseCase` enforces
`MAX_UPLOAD_SIZE`, and both are a refusal the caller must act on, so both name the file
limit — told to trim to the transport cap, a caller lands just above the application's
own check and is refused a second time.
"""


def bucket_for(method: str, path: str) -> str | None:
    """Which rate-limit bucket a request falls into, or `None` for unlimited (§8.1 step 3).

    Split by *operation*, not by HTTP verb: `POST /{id}/search` costs a query embedding
    plus a vector scan, nowhere near an ingest's parse/chunk/embed of a whole file, so
    grouping it with create/replace would price it by its verb instead of its work.

    Matches on prefix because it runs before routing, where `/{document_id}` is not parsed
    yet — the same reason the limiter can be consulted while the body is still on the wire.
    """
    if not path.startswith(_DOCUMENTS_PREFIX):
        return None
    if method == "POST" and path.rstrip("/") == _DOCUMENTS_PREFIX:
        return INGEST_BUCKET
    if method == "PUT":
        return INGEST_BUCKET
    return READ_BUCKET


def log_rejection(scope: Scope, *, outcome: str, detail: str | None = None) -> None:
    """Write the `op_completed` line for a request refused before it reached a route.

    Middleware answers without ever entering a handler, so nothing downstream would log
    these — and they are exactly the outcomes §8.7's metric filters count
    (`RateLimitExceededError`, `401`). Reads what earlier middleware left in the scope: the
    request id and timer are always there (request-id middleware is outermost), the token
    only once authentication has succeeded, which is why an auth failure logs no
    `client_id`.
    """
    state = scope.get("state", {})
    start = state.get("start_time")
    token = state.get("token")
    log_event(
        "op_completed",
        # WARNING, flat: every outcome this can be handed is the caller's own doing —
        # a missing header (422), bad credentials (401), an over-quota caller (429), an
        # over-sized body (413). None of them is the service failing, and none reaches
        # 5xx. The status itself never arrives here: `RejectionLogger`'s signature is
        # the library's, and it passes only `outcome` and `detail`.
        level=logging.WARNING,
        route=f"{scope['method']} {scope['path']}",
        outcome=outcome,
        duration_ms=(time.monotonic() - start) * 1000 if start is not None else 0.0,
        request_id=state.get("request_id"),
        client_id=getattr(token, "client_id", None),
        sub=getattr(token, "subject", None),
        # No `error_code`: it only ever held `outcome` again — see `errors._log_failure`.
        error_reason=detail,
    )


MISSING_REQUEST_ID_ERROR = MalformedRequestError()
"""What this service answers with when `X-Request-ID` is absent (§7.6, §8.1 step 1).

The requirement itself is platform-wide and lives in `holahost_http.RequestIdMiddleware`
(its `missing_header_error` argument) — both real entry paths attach the header
unconditionally, so its absence means a caller is misconfigured or bypassing the intended
path. The code and status that violation is answered with are this service's own
taxonomy, which is why the library takes them as an argument instead of owning them.

Mute by design — see `MalformedRequestError`. Which header was missing reaches the log
instead, through the middleware's own `on_rejected` call.
"""


__all__ = [
    "HEALTH_PATH",
    "INGEST_BUCKET",
    "MAX_REQUEST_BODY_SIZE",
    "MISSING_REQUEST_ID_ERROR",
    "RATE_LIMIT_WINDOW_SECONDS",
    "READ_BUCKET",
    "REPORTED_UPLOAD_LIMIT",
    "bucket_for",
    "log_rejection",
]
