"""holahost-http: the HTTP edge every Holahost service shares (LIB-02).

Three checks that must happen before a request reaches a route handler, plus the
error envelope they answer with. What is here is what a service cannot get right on
its own from inside the framework's request cycle — see each module for why.
"""

from holahost_http.body_limit import (
    MULTIPART_OVERHEAD_ALLOWANCE,
    BodySizeLimitMiddleware,
    body_cap_for_upload,
)
from holahost_http.errors import (
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
from holahost_http.rate_limit import CallerIdentity, RateLimiter, RateLimitMiddleware
from holahost_http.request_id import RequestIdMiddleware

__all__ = [
    "DEFAULT_MAX_TRACKED_KEYS",
    "MULTIPART_OVERHEAD_ALLOWANCE",
    "BodySizeLimitMiddleware",
    "CallerIdentity",
    "InMemoryRateLimiter",
    "PayloadTooLargeError",
    "PlatformError",
    "RateLimitExceededError",
    "RateLimitMiddleware",
    "RateLimiter",
    "RejectionLogger",
    "RequestIdMiddleware",
    "body_cap_for_upload",
    "error_envelope",
    "send_platform_error",
]
