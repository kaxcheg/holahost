"""Self-contained JWT/JWKS fixtures for the end-to-end tests in this directory, plus the
shared real-app `client` they build on.

Does not reuse holahost-auth's own conftest fixtures: pytest's conftest discovery only
walks ancestor directories of the test being run, and that file lives in a sibling package's
tree. A stdlib `http.server` in a background thread avoids both a new dev dependency and
cross-package `pytest_plugins` wiring.
"""

from __future__ import annotations

import datetime
import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlsplit

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from interface.http.api_base import SERVICE_NAME

_KID = "kid-1"
_ISSUER = "auth"


@pytest.fixture(scope="session")
def _rsa_keypair() -> tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture(scope="session")
def jwks_url(_rsa_keypair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]) -> Iterator[str]:
    """A real HTTP JWKS endpoint serving one fixed RS256 key, for the test session."""
    _, public_key = _rsa_keypair
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk["kid"] = _KID
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    body = json.dumps({"keys": [jwk]}).encode()

    class _JwksHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass  # silence request logging — keeps test output readable

    server = HTTPServer(("127.0.0.1", 0), _JwksHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/jwks.json"
    finally:
        server.shutdown()
        thread.join()


@pytest.fixture(scope="session")
def make_token(_rsa_keypair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]) -> Any:
    private_key, _ = _rsa_keypair

    def _make(*, sub: str, client_id: str) -> str:
        now = datetime.datetime.now(tz=datetime.UTC)
        claims = {
            "iss": _ISSUER,
            "aud": SERVICE_NAME,
            "sub": sub,
            "client_id": client_id,
            "iat": int(now.timestamp()),
            "exp": int((now + datetime.timedelta(minutes=5)).timestamp()),
        }
        return pyjwt.encode(claims, private_key, algorithm="RS256", headers={"kid": _KID})

    return _make


@pytest.fixture(scope="session")
def client(pg_dsn: str, jwks_url: str) -> Iterator[TestClient]:
    """Session-scoped, not per-test: `interface.http.dependencies`' `@lru_cache` singletons
    live for the whole process once built — matching how `bootstrap()` is meant to run
    exactly once per real process. One real app, one real environment, shared by every test
    in this directory; tokens are cheap to mint per test instead.
    """
    # `Settings` assembles `database_url` itself from these parts rather than reading one
    # pre-built DSN, so this fixture supplies its testcontainers-assigned host and port the
    # same way.
    dsn_parts = urlsplit(pg_dsn)
    assert dsn_parts.username and dsn_parts.password and dsn_parts.hostname and dsn_parts.port

    # `pytest.MonkeyPatch.context()`, not a session-scoped fixture: a session-scoped patch
    # holds these until the whole run's teardown, late enough to leak this container's random
    # port into unit tests collected afterwards.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ENV", "dev")
        mp.setenv("POSTGRES_USER", dsn_parts.username)
        mp.setenv("POSTGRES_PASSWORD", dsn_parts.password)
        mp.setenv("POSTGRES_DB", dsn_parts.path.lstrip("/"))
        mp.setenv("POSTGRES_HOST", dsn_parts.hostname)
        mp.setenv("POSTGRES_PORT", str(dsn_parts.port))
        mp.setenv("JWKS_URL", jwks_url)
        mp.setenv("EXPECTED_ALGORITHM", "RS256")
        mp.setenv("EXPECTED_ISSUER", _ISSUER)
        mp.setenv("EXPECTED_AUDIENCE", SERVICE_NAME)
        mp.setenv("JWT_CLOCK_SKEW_SECONDS", "30")

        # Import (not call) bootstrap — the module-level `app = bootstrap()` already runs it
        # exactly once, on this import, which is why the variables must still be set here.
        # Calling `bootstrap()` again would build a redundant second app and log a second,
        # misleadingly instant `startup_completed`.
        from scripts.bootstrap import app as built_app

    with TestClient(built_app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(make_token: Callable[..., str]) -> dict[str, str]:
    token = make_token(sub="user-123", client_id="cli-1")
    return {"Authorization": f"Bearer {token}", "X-Request-ID": "e2e-test-request-id"}
