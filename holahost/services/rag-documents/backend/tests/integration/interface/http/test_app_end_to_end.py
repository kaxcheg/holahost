"""End-to-end smoke test: create -> search -> get -> delete through the real app,
real Postgres, real JWT validation. Proves the composition root actually wires
(fakes in test_router.py can't catch a real wiring bug).

`client`/`auth_headers` fixtures live in `conftest.py` (shared with `test_grounding.py`, R-29).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

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
    response = client.get("/api/rag-documents/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_request_id_returns_422_against_the_real_app(
    client: TestClient, make_token: Callable[..., str]
) -> None:
    # test_edge.py proves the rule against a stubbed stack; this proves the real app,
    # with real auth resolved, enforces it too — and enforces it *before* auth: the token
    # below is valid, so a 422 here can only have come from the request-id check.
    token = make_token(sub="user-123", client_id="cli-1")

    response = client.get(
        "/api/rag-documents/documents/8f14e45f-ceea-467a-9f0a-1c2d3e4f5a6b",
        headers={"Authorization": f"Bearer {token}"},  # no X-Request-ID
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "MalformedRequestError"
    # Mute: the one error answered before authentication, so it names nothing a caller
    # could use to get past the check. The cause goes to the log.
    assert body["error"]["details"] == {}
    assert "X-Request-ID" not in response.text


def test_missing_token_returns_401_against_the_real_app(client: TestClient) -> None:
    # holahost-auth answers 401 from middleware, not via fastapi.HTTPException — this is
    # the one test proving the real stack refuses an unauthenticated request, rather than
    # the fakes in test_router.py matching it.
    response = client.get(
        "/api/rag-documents/documents/8f14e45f-ceea-467a-9f0a-1c2d3e4f5a6b",
        headers={"X-Request-ID": "e2e-test-request-id"},  # no Authorization at all
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


@contextmanager
def _attach(records: list[dict[str, Any]]) -> Iterator[None]:
    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if getattr(record, "event", None) == "op_completed":
                records.append(dict(record.__dict__))

    logger = logging.getLogger("holahost")
    handler = _Collector()
    logger.addHandler(handler)
    try:
        yield
    finally:
        logger.removeHandler(handler)


def test_ingest_and_search_report_their_own_cost(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """§8.7's `stage_ms` and `top_score`, against the real pipeline.

    Both fields were in the log allowlist and emitted by nothing. Without `stage_ms` a
    slow ingest is one opaque `duration_ms` — a scanned PDF that takes its time in parse
    looks exactly like model contention in embed. Without `top_score` there is no way to
    tell "the threshold is too high" from "this document has no answer", which is what
    `SIMILARITY_THRESHOLD` has to be calibrated against.
    """
    guidebook_text = (
        b"Check-in is at 15:00. Check-out is at 11:00. "
        b"The wifi password is posted on the fridge. "
        b"Parking is available in the garage behind the building. "
        b"For any issues, contact the host through the platform messaging system."
    )
    # Read off the logger directly, not stdout. The `holahost` logger sets
    # `propagate = False`, so `caplog` never sees these; and its stream handler holds the
    # real `sys.stdout` from when logging was configured at import, which puts the output
    # out of reach of pytest's own capture fixtures. Attaching a handler is deterministic
    # and needs none of that machinery.
    # `Any`, not `object`: these are log-record attributes whose types the allowlist in
    # `config/logging.py` already fixes; re-declaring them here would only duplicate it.
    events: list[dict[str, Any]] = []
    with _attach(events):
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

    ingest = next(e for e in events if e["route"] == "POST /documents")
    search = next(e for e in events if e["route"] == "POST /documents/{id}/search")

    assert set(ingest["stage_ms"]) == {"parse", "chunk", "embed", "persist"}
    assert all(ms >= 0 for ms in ingest["stage_ms"].values())
    # The four are a decomposition of the request, not four unrelated numbers: `persist`
    # is booked as the remainder, so they sum to the use case's own duration and cannot
    # exceed the request's.
    assert sum(ingest["stage_ms"].values()) <= ingest["duration_ms"] + 1.0

    assert search["top_score"] is not None, "the sample query matches this text"
    assert 0.0 <= search["top_score"] <= 1.0
    assert search["stage_ms"] is None, "search is not an ingest; it has no stages to report"

    client.delete(f"/api/rag-documents/documents/{document_id}", headers=auth_headers)
