"""Per-caller rate limiting, enforced before the body is read."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from starlette.types import ASGIApp, Receive, Scope, Send

from holahost_http.errors import (
    RateLimitExceededError,
    RejectionLogger,
    send_platform_error,
)


class CallerIdentity(Protocol):
    """The facts a limiter needs about who is calling.

    Structural on purpose: ``holahost_auth.TokenContext`` satisfies it as written,
    without this library importing the auth library — which would be backwards, since
    auth is the layer above.
    """

    @property
    def subject(self) -> str:
        """The caller's ``sub``."""

    @property
    def client_id(self) -> str:
        """The calling client's id."""

    @property
    def is_service_token(self) -> bool:
        """True when the caller is a service acting for itself, not for a user."""


class RateLimiter(Protocol):
    """Counts requests per caller per bucket and refuses those over the ceiling."""

    def check(self, *, client_id: str, subject: str, bucket: str, is_service: bool) -> None:
        """Check and increment the counter for this caller and bucket.

        Concurrency: check-and-increment must be atomic. Read-then-write lets two
        concurrent requests read the same pre-increment count and both pass, which a
        thread-pool process will do routinely.

        Args:
            client_id: The calling client's id.
            subject: The caller's ``sub``. Equals ``client_id`` for a service token.
            bucket: Which ceiling applies, e.g. ``"ingest"`` / ``"read"``.
            is_service: Whether the caller is a service token. Passed in rather than
                derived from ``subject == client_id`` inside the limiter: that
                equivalence is a fact about the token model and already has an owner.

        Raises:
            RateLimitExceededError: the caller is over its ceiling for this bucket.
        """
        ...


class RateLimitMiddleware:
    """Applies the limiter before routing — and therefore before the body is read.

    Ordering is the point: as a route dependency the check would run after the framework
    resolved the request body, so a caller already over quota still gets its upload read
    in full before being told 429. Here the counter is consulted while the body is still
    on the wire.

    Runs after authentication, which is what puts the caller in ``scope["state"]``, and
    expects it: a bucketed route no authentication covered is a wiring mistake, reported
    as one rather than silently unlimited.

    Args:
        limiter: The counter implementation.
        bucket_for: ``(method, path) -> bucket | None``, where ``None`` means this
            route is not rate limited. Given the raw path, before routing has parsed
            path parameters — so it matches on prefix and method, which is also why it
            can express "cost of the operation", not "shape of the verb" (a search
            posted to a sub-path is a read).
        on_rejected: Optional callback used to log a rejection.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter,
        bucket_for: Callable[[str, str], str | None],
        on_rejected: RejectionLogger | None = None,
    ) -> None:
        self.app = app
        self._limiter = limiter
        self._bucket_for = bucket_for
        self._on_rejected = on_rejected

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        bucket = self._bucket_for(scope["method"], scope["path"])
        if bucket is None:
            await self.app(scope, receive, send)
            return

        stored = scope.get("state", {}).get("token")
        if stored is None:
            raise RuntimeError(
                f"no authenticated caller in scope for a rate-limited route "
                f"({scope['method']} {scope['path']}) — authentication middleware must "
                f"run before RateLimitMiddleware"
            )
        # cast, not isinstance: a runtime-checkable protocol would only verify attribute
        # presence, and anything else here fails on the next line anyway.
        caller = cast(CallerIdentity, stored)

        try:
            self._limiter.check(
                client_id=caller.client_id,
                subject=caller.subject,
                bucket=bucket,
                is_service=caller.is_service_token,
            )
        except RateLimitExceededError as exc:
            if self._on_rejected is not None:
                self._on_rejected(scope, outcome=exc.code)
            await send_platform_error(
                scope,
                receive,
                send,
                status=429,
                error=exc,
                headers={"Retry-After": str(exc.retry_after)},
            )
            return

        await self.app(scope, receive, send)
