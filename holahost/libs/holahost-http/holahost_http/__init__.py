"""holahost-http: the HTTP edge every Holahost service shares (LIB-02).

Two halves, both of them things a service cannot get right on its own from inside the
framework's request cycle:

* the checks that must happen *before* a request reaches a route handler — request id,
  body size, authentication's slot, rate limit — and the envelope they answer with;
* the mapping from an exception to that envelope once a route has raised, together with
  the published shape of the errors this package itself defines.

What stays with the service is its vocabulary: which errors exist, what status each
answers with, and what its ``details`` carry.
"""

from holahost_http.body_limit import (
    MULTIPART_OVERHEAD_ALLOWANCE,
    BodySizeLimitMiddleware,
    body_cap_for_upload,
)
from holahost_http.edge import create_edge_app
from holahost_http.error_handlers import ErrorContract, register_error_handlers
from holahost_http.errors import (
    INTERNAL_ERROR_CODE,
    InvalidPayloadError,
    MalformedRequestError,
    NotFoundError,
    PayloadTooLargeError,
    PlatformError,
    RateLimitExceededError,
    RejectionLogger,
    error_envelope,
    send_platform_error,
)
from holahost_http.in_memory_rate_limiter import (
    DEFAULT_MAX_TRACKED_KEYS,
    InMemoryRateLimiter,
)
from holahost_http.observability import log_rejection
from holahost_http.rate_limit import CallerIdentity, RateLimiter, RateLimitMiddleware
from holahost_http.request_id import RequestIdMiddleware
from holahost_http.security import BEARER_SCHEME_NAME, bearer_scheme

__all__ = [
    "BEARER_SCHEME_NAME",
    "DEFAULT_MAX_TRACKED_KEYS",
    "INTERNAL_ERROR_CODE",
    "MULTIPART_OVERHEAD_ALLOWANCE",
    "BodySizeLimitMiddleware",
    "CallerIdentity",
    "ErrorContract",
    "InMemoryRateLimiter",
    "InvalidPayloadError",
    "MalformedRequestError",
    "NotFoundError",
    "PayloadTooLargeError",
    "PlatformError",
    "RateLimitExceededError",
    "RateLimitMiddleware",
    "RateLimiter",
    "RejectionLogger",
    "RequestIdMiddleware",
    "bearer_scheme",
    "body_cap_for_upload",
    "create_edge_app",
    "error_envelope",
    "log_rejection",
    "register_error_handlers",
    "send_platform_error",
]
