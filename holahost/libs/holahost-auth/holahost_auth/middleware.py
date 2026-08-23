"""Authentication as ASGI middleware — validation before routing."""

from __future__ import annotations

from collections.abc import Sequence

from holahost_http.errors import RejectionLogger
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from holahost_auth.config import AuthConfig
from holahost_auth.exceptions import AuthenticationError, JwksUnavailableError
from holahost_auth.jwks import build_jwks_client
from holahost_auth.validator import authenticate

# The suppression below is for ruff's hardcoded-password heuristic, which fires on the
# constant's name. This is a dict key, and it is exported API — `request.state.token` is
# what every consuming route reads. Renaming it to dodge a false positive would leave the
# constant lying about its own value.
TOKEN_SCOPE_KEY = "token"  # noqa: S105


class HolahostAuthMiddleware:
    """Validates the bearer token before the request reaches routing.

    Placing this ahead of routing is not a preference. A framework resolves the
    request body while building the endpoint's arguments, which happens *before* it
    resolves that endpoint's dependencies — so authentication expressed as a
    dependency runs after an upload has already been read in full. Every
    unauthenticated caller then gets to spend the service's bandwidth and memory
    before being told 401.

    Stores the validated ``TokenContext`` at ``scope["state"]["token"]``, which is
    what ``request.state.token`` reads, so handlers receive it the usual way (see
    ``current_token``) and later middleware — rate limiting — can read it too.

    Failures are answered here, not raised: an exception thrown from middleware flies
    past the app's own exception handlers (they are bound inside the middleware stack)
    and becomes a 500. Neither body carries a reason — 401 discloses nothing that would
    help someone probe for one (the cause is logged, never returned), and 503 is about
    the service's own state, not the caller's token.

    Args:
        config: This service's validation configuration.
        public_paths: Exact paths served without authentication — health checks.
        on_rejected: Optional callback used to log a rejection.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        config: AuthConfig,
        public_paths: Sequence[str] = (),
        on_rejected: RejectionLogger | None = None,
    ) -> None:
        self.app = app
        self._config = config
        self._jwks_client = build_jwks_client(config.jwks_url)
        self._public_paths = frozenset(public_paths)
        self._on_rejected = on_rejected

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self._public_paths:
            await self.app(scope, receive, send)
            return

        authorization: str | None = None
        for raw_name, raw_value in scope["headers"]:
            if raw_name.lower() == b"authorization":
                authorization = raw_value.decode("latin-1")
                break

        try:
            token = authenticate(authorization, config=self._config, jwks_client=self._jwks_client)
        except AuthenticationError as exc:
            await self._refuse(scope, receive, send, 401, "Unauthorized", exc.reason)
            return
        except JwksUnavailableError as exc:
            # An unreachable or malformed JWKS endpoint would reject every otherwise
            # valid token. Reporting that as 401 would dress a live incident up as a
            # wave of bad credentials.
            await self._refuse(scope, receive, send, 503, "Service Unavailable", exc.reason)
            return

        scope.setdefault("state", {})[TOKEN_SCOPE_KEY] = token
        await self.app(scope, receive, send)

    async def _refuse(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        detail: str,
        reason: str,
    ) -> None:
        if self._on_rejected is not None:
            self._on_rejected(scope, outcome=str(status), detail=reason)
        response = JSONResponse(status_code=status, content={"detail": detail})
        await response(scope, receive, send)
