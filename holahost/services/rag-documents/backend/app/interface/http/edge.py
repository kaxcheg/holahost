"""Everything the shared middleware needs to know about *this* service.

`holahost-http` and `holahost-auth` supply the mechanisms — request-id propagation, a
body-size cap, authentication, a rate limiter — deliberately without opinions about which
routes they apply to, how big is too big, what a rejection is called on the wire, or how
it is logged. Those are this service's contract, and they all live here: one module for
the values and rules the edge is parameterised with, so `app.py` is left holding nothing
but the wiring.

`api_base.py` stays separate and minimal: the container healthcheck imports it directly,
so it must not drag in the application layer to answer "what is my base path".
"""

from __future__ import annotations

from holahost_http import MalformedRequestError, body_cap_for_upload

from application.limits import MAX_UPLOAD_SIZE
from interface.http.api_base import API_BASE_URL

_DOCUMENTS_PREFIX = f"{API_BASE_URL}/documents"
HEALTH_PATH = f"{API_BASE_URL}/health"

# Shared vocabulary: `bucket_for` maps a request to a bucket, `dependencies.
# get_rate_limiter` maps a bucket to a ceiling. Naming them in either place would only
# pick which one imports the other.
INGEST_BUCKET = "ingest"
READ_BUCKET = "read"

# The unit every RATE_LIMIT_* setting is counted in. A constant rather than a
# setting: the window is what those numbers *mean*, and halving it would silently halve
# every ceiling while the .env files went on claiming 60 and 600.
RATE_LIMIT_WINDOW_SECONDS = 3600

# A transport limit: it bounds the whole HTTP body, multipart framing included, and only
# decides how much the edge reads before anyone can look. `MAX_UPLOAD_SIZE` stays the
# application's own check on the extracted file. Derived so the two cannot drift.
MAX_REQUEST_BODY_SIZE = body_cap_for_upload(MAX_UPLOAD_SIZE)

REPORTED_UPLOAD_LIMIT = MAX_UPLOAD_SIZE
"""The `limit` a 413 from either size gate advertises.

The middleware enforces `MAX_REQUEST_BODY_SIZE`, `CreateDocumentUseCase` enforces
`MAX_UPLOAD_SIZE`, and both are a refusal the caller must act on, so both name the file
limit — told to trim to the transport cap, a caller lands just above the application's
own check and is refused a second time.
"""


def bucket_for(method: str, path: str) -> str | None:
    """Which rate-limit bucket a request falls into, or `None` for unlimited.

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


MISSING_REQUEST_ID_ERROR = MalformedRequestError()
"""What this service answers with when `X-Request-ID` is absent.

The requirement lives in `holahost_http.RequestIdMiddleware` (its `missing_header_error`
argument) — both real entry paths attach the header unconditionally, so its absence means
a caller is misconfigured or bypassing the intended path. Which error that violation is
answered with is still the service's decision, which is why the library takes it as an
argument rather than raising one of its own: this service names the platform's mute
`MalformedRequestError`, and the status it carries is set beside it in `app.py`.
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
]
