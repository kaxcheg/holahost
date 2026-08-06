from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from holahost_auth.config import AuthConfig
from holahost_auth.context import TokenContext
from holahost_auth.dependency import HolahostAuth


def build_app(config: AuthConfig) -> FastAPI:
    app = FastAPI()
    auth = HolahostAuth(config)

    @app.get("/protected")
    def protected(ctx: Annotated[TokenContext, Depends(auth)]) -> dict[str, str]:
        return {"subject": ctx.subject}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_valid_token_returns_200(
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


def test_health_is_reachable_without_a_token(config: AuthConfig) -> None:
    client = TestClient(build_app(config))
    response = client.get("/health")
    assert response.status_code == 200


def test_jwks_unavailable_returns_503_not_401(
    make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    unreachable = AuthConfig(
        jwks_url="http://127.0.0.1:1/jwks.json",
        expected_algorithm="RS256",
        expected_issuer="auth",
        expected_audience="rag-documents",
        clock_skew_seconds=30,
    )
    client = TestClient(build_app(unreachable))
    token = make_token(kid="kid-1", claims={**base_claims, "sub": "u", "client_id": "c"})
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503
