"""Self-contained JWT/JWKS test fixtures for the real end-to-end test.

Deliberately does not reuse holahost-auth's own conftest fixtures (`jwks_server`/
`make_token`/`base_claims`, `holahost/libs/holahost-auth/tests/conftest.py`): pytest's
conftest discovery only walks ancestor directories of the test being run, and that
file lives in a sibling package's own `tests/` tree, not this repo's. Reusing it would
need either `pytest-httpserver` as a new dev dependency (holahost-auth's own choice)
or fragile cross-package `pytest_plugins` wiring. A stdlib `http.server` in a
background thread needs neither — `pyjwt`/`cryptography` are already transitively
available here via holahost-auth's own runtime dependency.
"""

from __future__ import annotations

import datetime
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

_KID = "kid-1"


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
def make_token(
    _rsa_keypair: tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey],
) -> Any:
    private_key, _ = _rsa_keypair

    def _make(*, sub: str, client_id: str) -> str:
        now = datetime.datetime.now(tz=datetime.UTC)
        claims = {
            "iss": "auth",
            "aud": "rag-documents",
            "sub": sub,
            "client_id": client_id,
            "iat": int(now.timestamp()),
            "exp": int((now + datetime.timedelta(minutes=5)).timestamp()),
        }
        return pyjwt.encode(claims, private_key, algorithm="RS256", headers={"kid": _KID})

    return _make
