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

# noqa: ruff's hardcoded-password heuristic fires on the name. This is a dict key, and an
# exported one — `request.state.token` is what consuming routes read.
TOKEN_SCOPE_KEY = "token"  # noqa: S105


class HolahostAuthMiddleware:
    """Validates the bearer token before the request reaches routing.

    Ahead of routing because a framework resolves the request body while building the
    endpoint's arguments, before its dependencies run — so authentication written as a
    dependency lets every unauthenticated caller spend the service's bandwidth and memory
    on a full upload before being told 401.

    Stores the validated ``TokenContext`` at ``scope["state"]["token"]``, which is what
    ``request.state.token`` reads, so handlers (see ``current_token``) and later
    middleware such as rate limiting both see it.

    Failures are answered here, not raised: an exception from middleware flies past the
    app's exception handlers, bound inside the stack, and becomes a 500. Neither body
    carries a reason — the cause is logged instead.

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
