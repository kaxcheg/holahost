"""Protocol for the per-caller rate limiter.

Consumed by interface-layer middleware (§8.1 step 3), not by any use case here —
the check happens before a use case is invoked. Stays an application-layer port
anyway: same reasoning as ``holahost-auth`` (LIB-01) being a real library rather
than inline middleware code — it encodes a business rule (per-bucket quotas,
US-R08), not a storage detail. Implemented by ticket R-18 (in-memory, per-bucket
counters) — a common platform pattern, not yet extracted to a shared lib since
counters are process-local by design (A-8).
"""

from __future__ import annotations

from typing import Protocol


class RateLimitExceededError(Exception):
    """The caller is over its rate limit for the given bucket.

    ``code`` mirrors the pattern every ``ApplicationError`` subclass follows (§7.6
    wire taxonomy) even though this type doesn't inherit from ``ApplicationError`` —
    it's a port-level exception (§8.0), not an application one; see the module
    docstring for why it stays a port anyway. Declaring ``code`` here means the
    interface layer's error handler reads it off the exception instead of
    duplicating the literal string itself.

    Args:
        retry_after: Seconds the caller should wait before retrying — for the
            middleware to surface as the ``Retry-After`` response header.
    """

    code = "ERR_RATE_LIMIT"

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limit exceeded, retry after {retry_after}s")
        self.retry_after = retry_after


class RateLimiter(Protocol):
    """In-memory per-``client_id``+``subject`` request-rate limiter."""

    def check(self, client_id: str, subject: str, bucket: str) -> None:
        """Check and increment the counter for ``(client_id, subject, bucket)``.

        Concurrency: check-and-increment must be atomic — guard the counter with a
        lock (e.g. one ``threading.Lock`` per bucket key) or an atomic primitive; a
        plain read-then-write lets two concurrent requests both read the same
        pre-increment count and both pass, leaking the limit. Not comparable in
        cost to ``VectorSearch.top_k`` avoiding a DB row lock: this is an in-process
        mutex around an integer increment (nanoseconds, no network, contends only
        with another thread doing the same tiny op) — not a cross-transaction lock
        whose wait time depends on someone else's DB round trip.

        Args:
            client_id: The caller's client id from the token.
            subject: The caller's subject (``sub``) from the token.
            bucket: ``"ingest"`` for create/replace, ``"read"`` for the rest.

        Raises:
            RateLimitExceededError: the caller is over its limit for this bucket.
        """
        ...
