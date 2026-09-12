"""Grounding contract test: a document with a unique sentinel fact must be findable by that
fact. Catches retrieval regressions unit tests cannot see — a wrong threshold, missing
normalization, or a mismatch between the ingest and query models — using real pgvector and the
real embedding model, no fakes.

Reuses the same `client`/`auth_headers` fixtures as `test_app_end_to_end.py` (real app, real
Postgres, real JWT validation via the local JWKS test server in conftest.py) rather than
introducing a second app-wiring pattern.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_sentinel_fact_is_retrievable_after_ingest(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    sentinel = f"sentinel-fact-{uuid.uuid4().hex}"
    # > MIN_EXTRACTED_TEXT_CHARS (200), same margin as test_app_end_to_end.py's own fixture text.
    content = (
        f"This guidebook mentions {sentinel} as a unique identifying fact. "
        "The rest of this document is unrelated filler text so the chunk containing "
        "the sentinel is not the only content the embedding model has to work with, "
        "matching how a real multi-fact guidebook is structured in practice."
    ).encode()

    create_resp = client.post(
        "/api/rag-documents/documents",
        files={"file": ("grounding.txt", content, "text/plain")},
        data={"name": "grounding-test-doc"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    document_id = create_resp.json()["document_id"]

    search_resp = client.post(
        f"/api/rag-documents/documents/{document_id}/search",
        json={"query": f"What mentions {sentinel}?"},
        headers=auth_headers,
    )
    assert search_resp.status_code == 200, search_resp.text
    chunks = search_resp.json()["chunks"]
    assert any(sentinel in chunk["text"] for chunk in chunks), chunks

    client.delete(f"/api/rag-documents/documents/{document_id}", headers=auth_headers)
