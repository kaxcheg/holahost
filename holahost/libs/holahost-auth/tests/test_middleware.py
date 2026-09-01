from collections.abc import Callable
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.middleware import Middleware
from starlette.types import Scope

from holahost_auth.config import AuthConfig
from holahost_auth.context import TokenContext
from holahost_auth.dependency import current_token
from holahost_auth.middleware import HolahostAuthMiddleware

UNREACHABLE_JWKS = AuthConfig(
    jwks_url="http://127.0.0.1:1/jwks.json",
    expected_algorithm="RS256",
    expected_issuer="auth",
    expected_audience="rag-documents",
    jwt_clock_skew_seconds=30,
)


def build_app(config: AuthConfig, on_rejected: Any = None) -> FastAPI:
    """A consuming service's whole wiring: one middleware, no exception handlers.

    Nothing here registers a handler for `AuthenticationError`/`JwksUnavailableError`,
    and that is the point — the middleware answers before routing, so those exceptions
    never leave it.
    """
    app = FastAPI(
        middleware=[
            Middleware(
                HolahostAuthMiddleware,
                config=config,
                public_paths=("/health",),
                on_rejected=on_rejected,
            )
        ]
    )

    @app.get("/protected")
    def protected(ctx: Annotated[TokenContext, Depends(current_token)]) -> dict[str, str]:
        return {"subject": ctx.subject}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_valid_token_reaches_the_route(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    client = TestClient(build_app(config))
    token = make_token(kid="kid-1", claims={**base_claims, "sub": "u", "client_id": "c"})
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"subject": "u"}


def test_missing_token_returns_401_without_reason_in_body(config: AuthConfig) -> None:
    client = TestClient(build_app(config))
    response = client.get("/protected")
    assert response.status_code == 401
    assert "reason" not in response.text and "missing" not in response.text.lower()


def test_public_path_is_reachable_without_a_token(config: AuthConfig) -> None:
    client = TestClient(build_app(config))
    assert client.get("/health").status_code == 200


def test_jwks_unavailable_returns_503_not_401(
    make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    client = TestClient(build_app(UNREACHABLE_JWKS))
    token = make_token(kid="kid-1", claims={**base_claims, "sub": "u", "client_id": "c"})
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503


def test_rejection_is_reported_to_the_logger(config: AuthConfig) -> None:
    """A request refused before routing still has to produce the caller's log line —
    nothing downstream of the middleware runs to write one."""
    recorded: list[tuple[str, str | None]] = []

    def on_rejected(scope: Scope, *, outcome: str, detail: str | None = None) -> None:
        recorded.append((outcome, detail))

    client = TestClient(build_app(config, on_rejected=on_rejected))
    client.get("/protected")

    assert len(recorded) == 1
    outcome, detail = recorded[0]
    assert outcome == "401"
    assert detail  # the cause is reported to the service, never to the caller
    assert detail not in client.get("/protected").text


def test_authenticated_route_is_reached_without_the_dependency_resolving_twice(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    """`current_token` reads state; it does not re-validate.

    The route declares no `Authorization` parameter and nothing re-reads the header,
    so the token reaching the handler can only be the one the middleware stored.
    """
    app = FastAPI(middleware=[Middleware(HolahostAuthMiddleware, config=config, public_paths=())])

    @app.get("/protected")
    def protected(ctx: Annotated[TokenContext, Depends(current_token)]) -> dict[str, str]:
        return {"client_id": ctx.client_id}

    token = make_token(kid="kid-1", claims={**base_claims, "sub": "u", "client_id": "c"})
    response = TestClient(app).get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"client_id": "c"}


def test_route_without_the_middleware_is_a_wiring_error_not_a_401() -> None:
    """An unauthenticated route reported as 401 would blame the caller for a defect."""
    app = FastAPI()

    @app.get("/protected")
    def protected(ctx: Annotated[TokenContext, Depends(current_token)]) -> dict[str, str]:
        return {"subject": ctx.subject}

    with pytest.raises(RuntimeError, match="HolahostAuthMiddleware"):
        TestClient(app, raise_server_exceptions=True).get("/protected")
