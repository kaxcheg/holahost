"""End-to-end smoke test: create -> search -> get -> delete through the real app,
real Postgres, real JWT validation. Proves the composition root actually wires
(fakes in test_router.py can't catch a real wiring bug).

`client`/`auth_headers` fixtures live in `conftest.py` (shared with `test_grounding.py`, R-29).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

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
