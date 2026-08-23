"""Self-contained JWT/JWKS test fixtures for the real end-to-end tests in this directory
(`test_app_end_to_end.py`, `test_grounding.py`), plus the shared real-app `client` fixture both
files build on.

Deliberately does not reuse holahost-auth's own conftest fixtures (`jwks_server`/
`make_token`/`base_claims`, `holahost/libs/holahost-auth/tests/conftest.py`): pytest's
conftest discovery only walks ancestor directories of the test being run, and that
file lives in a sibling package's own `tests/` tree, not this repo's. Reusing it would
need either `pytest-httpserver` as a new dev dependency (holahost-auth's own choice)
or fragile cross-package `pytest_plugins` wiring. A stdlib `http.server` in a
background thread needs neither — `pyjwt`/`cryptography` are already transitively
available here via holahost-auth's own runtime dependency.

`client`/`auth_headers` originally lived in `test_app_end_to_end.py` only; moved here (R-29) once
a second file in this directory (`test_grounding.py`) needed them too — pytest fixtures defined in
a test module aren't visible to sibling test modules, only fixtures in `conftest.py` are shared
across a directory.
"""

from __future__ import annotations

import datetime
import json
import tempfile
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

_KID = "kid-1"

# Not tempfile.TemporaryDirectory(): that auto-deletes on context exit, forcing a full
# model re-download every run. A stable subdirectory under the real system temp dir
# (tempfile.gettempdir(), not a literal "/tmp/..." string — S108) persists the
# ~100+ MB model across test runs, matching FastembedEmbeddingModel's own real
# production caching behavior (§3.1: loaded once per process into a volume).
_EMBEDDING_CACHE_DIR = str(Path(tempfile.gettempdir()) / "rag-documents-test-fastembed-cache")


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


@pytest.fixture(scope="session")
def client(pg_dsn: str, jwks_url: str) -> Iterator[TestClient]:
    """Session-scoped, not per-test: `interface.http.dependencies`' `@lru_cache` singletons
    (`get_settings`/`get_engine`/`get_embedding_model`/...) live for the whole process once
    built — matching how `bootstrap()` is meant to run exactly once per real process. One real
    app, one real environment, shared by every test in this directory; auth tokens are cheap to
    mint per test instead.
    """
    # Settings assembles database_url itself (config.settings — a @computed_field via
    # PostgresDsn) from these parts rather than reading one pre-built DATABASE_URL — this
    # fixture supplies its testcontainers-assigned host/port the same way, not a full DSN.
    dsn_parts = urlsplit(pg_dsn)
    assert dsn_parts.username and dsn_parts.password and dsn_parts.hostname and dsn_parts.port

    # `pytest.MonkeyPatch.context()`, not a session-scoped `monkeypatch` fixture: every one of
    # these env vars is read exactly once, at the `scripts.bootstrap` import below (Settings()
    # is built once behind interface.http.dependencies' @lru_cache and never re-reads os.environ
    # afterward), so nothing past that import needs them still set — a session-scoped patch
    # would hold them until the whole `pytest` session's teardown instead, which is late enough
    # to leak into unrelated tests collected later in the same unfiltered `pytest` run. Found for
    # real, not guessed: a bare `pytest` run (no `-m` filter, same command `make ci-local` uses)
    # collects this directory before `tests/unit/`, and did leak POSTGRES_HOST/PORT (this
    # fixture's testcontainers-assigned port) into `tests/unit/config/test_settings.py`'s
    # assertions, which expect the fixed `postgres:5432` default.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ENV", "dev")
        mp.setenv("POSTGRES_USER", dsn_parts.username)
        mp.setenv("POSTGRES_PASSWORD", dsn_parts.password)
        mp.setenv("POSTGRES_DB", dsn_parts.path.lstrip("/"))
        mp.setenv("POSTGRES_HOST", dsn_parts.hostname)
        mp.setenv("POSTGRES_PORT", str(dsn_parts.port))
        mp.setenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        mp.setenv("EMBEDDING_CACHE_DIR", _EMBEDDING_CACHE_DIR)
        mp.setenv("CHUNK_WINDOW_TOKENS", "120")
        mp.setenv("CHUNK_OVERLAP_TOKENS", "16")
        mp.setenv("SEARCH_TOP_K", "5")
        mp.setenv("SIMILARITY_THRESHOLD", "0.30")
        mp.setenv("MAX_QUERY_LENGTH", "4000")
        mp.setenv("RATE_LIMIT_USER_INGEST", "60")
        mp.setenv("RATE_LIMIT_USER_READ", "600")
        mp.setenv("RATE_LIMIT_SERVICE_INGEST", "60")
        mp.setenv("RATE_LIMIT_SERVICE_READ", "600")
        mp.setenv("JWT_CLOCK_SKEW_SECONDS", "30")
        mp.setenv("JWKS_URL", jwks_url)
        mp.setenv("EXPECTED_ALGORITHM", "RS256")
        mp.setenv("EXPECTED_ISSUER", "auth")
        mp.setenv("EXPECTED_AUDIENCE", "rag-documents")

        # Import (not call) bootstrap — the module-level `app = bootstrap()` statement in
        # scripts/bootstrap.py already runs bootstrap() exactly once, on this very import,
        # which is why env vars must still be set at this point. Calling bootstrap() again
        # here would build a redundant second FastAPI app (the @lru_cache singletons make it
        # cheap, but it's pointless duplication and logs a second, misleadingly-instant
        # "startup_completed" event).
        from scripts.bootstrap import app as built_app

    with TestClient(built_app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(make_token: Callable[..., str]) -> dict[str, str]:
    token = make_token(sub="user-123", client_id="cli-1")
    return {"Authorization": f"Bearer {token}", "X-Request-ID": "e2e-test-request-id"}
