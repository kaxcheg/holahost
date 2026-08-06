import datetime
import json
from collections.abc import Callable
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pytest_httpserver import HTTPServer
from werkzeug import Request, Response

from holahost_auth.config import AuthConfig


@pytest.fixture
def rsa_keypair() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def jwk_for(
    rsa_keypair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey],
) -> Callable[[str], dict[str, Any]]:
    _, public_key = rsa_keypair

    def _build(kid: str) -> dict[str, Any]:
        jwk: dict[str, Any] = RSAAlgorithm.to_jwk(public_key, as_dict=True)
        jwk["kid"] = kid
        jwk["use"] = "sig"
        jwk["alg"] = "RS256"
        return jwk

    return _build


class JwksServerControl:
    """Test control surface for a fake JWKS endpoint: swap its served key set mid-test."""

    def __init__(self, url: str, jwk_for: Callable[[str], dict[str, Any]]) -> None:
        self.url = url
        self._jwk_for = jwk_for
        self._keys: list[dict[str, Any]] = []

    def __call__(self, *kids: str) -> None:
        self._keys = [self._jwk_for(kid) for kid in kids]

    def as_json(self) -> str:
        return json.dumps({"keys": self._keys})


@pytest.fixture
def jwks_server(
    httpserver: HTTPServer, jwk_for: Callable[[str], dict[str, Any]]
) -> JwksServerControl:
    """A JWKS endpoint whose served key set can be swapped mid-test."""
    control = JwksServerControl(httpserver.url_for("/jwks.json"), jwk_for)

    def handler(_request: Request) -> Response:
        return Response(control.as_json(), mimetype="application/json")

    httpserver.expect_request("/jwks.json").respond_with_handler(handler)
    return control


@pytest.fixture
def make_token(
    rsa_keypair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey],
) -> Callable[..., str]:
    private_key, _ = rsa_keypair

    def _make(*, kid: str, claims: dict[str, Any]) -> str:
        return pyjwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})

    return _make


@pytest.fixture
def base_claims() -> dict[str, Any]:
    now = datetime.datetime.now(tz=datetime.UTC)
    return {
        "iss": "auth",
        "aud": "rag-documents",
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(minutes=5)).timestamp()),
    }


@pytest.fixture
def config(jwks_server: JwksServerControl) -> AuthConfig:
    jwks_server("kid-1")
    return AuthConfig(
        jwks_url=jwks_server.url,
        expected_algorithm="RS256",
        expected_issuer="auth",
        expected_audience="rag-documents",
        clock_skew_seconds=30,
    )
