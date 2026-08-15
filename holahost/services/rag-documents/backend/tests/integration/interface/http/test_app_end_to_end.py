"""End-to-end smoke test: create -> search -> get -> delete through the real app,
real Postgres, real JWT validation. Proves the composition root actually wires
(fakes in test_router.py can't catch a real wiring bug).

`client` is session-scoped, not per-test: `interface.http.dependencies`' `@lru_cache`
singletons (`get_settings`/`get_engine`/`get_embedding_model`/...) live for the whole
process once built — matching how `bootstrap()` is meant to run exactly once per real
process. A per-test fixture rebuilding the app would just resolve those same cached
singletons a second time anyway (a monkeypatched env change on a later test would be
silently ignored), so the honest scope is session: one real app, one real environment,
for every test in this file. Auth tokens are cheap to mint per test instead.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Not tempfile.TemporaryDirectory(): that auto-deletes on context exit, forcing a full
# model re-download every run. A stable subdirectory under the real system temp dir
# (tempfile.gettempdir(), not a literal "/tmp/..." string — S108) persists the
# ~100+ MB model across test runs, matching FastembedEmbeddingModel's own real
# production caching behavior (§3.1: loaded once per process into a volume).
_EMBEDDING_CACHE_DIR = str(Path(tempfile.gettempdir()) / "rag-documents-test-fastembed-cache")


@pytest.fixture(scope="session")
def client(
    pg_dsn: str, jwks_url: str, monkeypatch_session: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch_session.setenv("ENV", "dev")
    monkeypatch_session.setenv("DATABASE_URL", pg_dsn)
    monkeypatch_session.setenv(
        "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    monkeypatch_session.setenv("EMBEDDING_CACHE_DIR", _EMBEDDING_CACHE_DIR)
    monkeypatch_session.setenv("CHUNK_WINDOW_TOKENS", "120")
    monkeypatch_session.setenv("CHUNK_OVERLAP_TOKENS", "16")
    monkeypatch_session.setenv("SEARCH_TOP_K", "5")
    monkeypatch_session.setenv("SIMILARITY_THRESHOLD", "0.30")
    monkeypatch_session.setenv("MAX_QUERY_LENGTH", "4000")
    monkeypatch_session.setenv("RATE_LIMIT_DEFAULT", "600")
    monkeypatch_session.setenv("RATE_LIMIT_INGEST", "60")
    monkeypatch_session.setenv("JWT_CLOCK_SKEW_SECONDS", "30")
    monkeypatch_session.setenv("JWKS_URL", jwks_url)
    monkeypatch_session.setenv("EXPECTED_ALGORITHM", "RS256")
    monkeypatch_session.setenv("EXPECTED_ISSUER", "auth")
    monkeypatch_session.setenv("EXPECTED_AUDIENCE", "rag-documents")

    # Import (not call) bootstrap — the module-level `app = bootstrap()` statement in
    # scripts/bootstrap.py already runs bootstrap() exactly once, on this very import,
    # which is why env vars must already be correct before it happens. Calling
    # bootstrap() again here would build a redundant second FastAPI app (the
    # @lru_cache singletons make it cheap, but it's pointless duplication and logs a
    # second, misleadingly-instant "startup_completed" event).
    from scripts.bootstrap import app as built_app

    with TestClient(built_app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    """`monkeypatch` itself is function-scoped only; `client` needs a session-scoped
    equivalent to set env vars once for the one real app built for this whole file."""
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture
def auth_headers(make_token: Callable[..., str]) -> dict[str, str]:
    token = make_token(sub="user-123", client_id="cli-1")
    return {"Authorization": f"Bearer {token}", "X-Request-ID": "e2e-test-request-id"}


pytestmark = pytest.mark.integration


def test_create_search_get_delete_round_trip(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # > MIN_EXTRACTED_TEXT_CHARS (200) — real pipeline, real check, not mocked.
    guidebook_text = (
        b"Check-in is at 15:00. Check-out is at 11:00. "
        b"The wifi password is posted on the fridge. "
        b"Parking is available in the garage behind the building. "
        b"For any issues, contact the host through the platform messaging system. "
        b"Quiet hours are from 22:00 to 08:00."
    )
    create_resp = client.post(
        "/api/rag-documents/documents",
        files={"file": ("guide.txt", guidebook_text, "text/plain")},
        data={"name": "Guidebook"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    document_id = create_resp.json()["document_id"]

    search_resp = client.post(
        f"/api/rag-documents/documents/{document_id}/search",
        json={"query": "what time is check-in"},
        headers=auth_headers,
    )
    assert search_resp.status_code == 200, search_resp.text

    get_resp = client.get(f"/api/rag-documents/documents/{document_id}", headers=auth_headers)
    assert get_resp.status_code == 200

    delete_resp = client.delete(f"/api/rag-documents/documents/{document_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    get_after_delete = client.get(
        f"/api/rag-documents/documents/{document_id}", headers=auth_headers
    )
    assert get_after_delete.status_code == 404


def test_health_is_public_and_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_request_id_returns_422_against_the_real_app(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    # Fakes in test_router.py can prove the dependency wiring in isolation; this
    # proves the real app, with real auth resolved, actually enforces it too.
    token = make_token(sub="user-123", client_id="cli-1")

    response = client.get(
        "/api/rag-documents/documents/8f14e45f-ceea-467a-9f0a-1c2d3e4f5a6b",
        headers={"Authorization": f"Bearer {token}"},  # no X-Request-ID
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "ERR_INVALID_PAYLOAD"
    assert body["error"]["details"] == {"field": "X-Request-ID"}


def test_missing_token_returns_401_against_the_real_app(client: TestClient) -> None:
    # holahost-auth raises AuthenticationError directly (not fastapi.HTTPException,
    # see clarifications.md) — this is the one test proving errors.py's own
    # handle_authentication_error is actually wired to catch it for real, not just
    # matched by the fakes in test_router.py.
    response = client.get(
        "/api/rag-documents/documents/8f14e45f-ceea-467a-9f0a-1c2d3e4f5a6b",
        headers={"X-Request-ID": "e2e-test-request-id"},  # no Authorization at all
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
