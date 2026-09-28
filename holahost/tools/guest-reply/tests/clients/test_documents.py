"""`rag-documents`: one call per operation, the file sent as is."""

from __future__ import annotations

from typing import Any

import httpx
from pytest_httpserver import HTTPServer

from guest_reply.clients.documents import API_BASE, CreatedDocument, DocumentsClient
from tests._support import (
    DOCUMENT,
    DOCUMENT_ID,
    DOCUMENTS,
    SEARCH,
    caller,
    calls,
    capture_upload,
    created,
    hits,
)


def _client(httpserver: HTTPServer, http: httpx.Client) -> DocumentsClient:
    return DocumentsClient(caller(httpserver, http, API_BASE))


def test_create_sends_the_file_and_the_name(httpserver: HTTPServer, http: httpx.Client) -> None:
    seen: list[dict[str, Any]] = []
    httpserver.expect_request(DOCUMENTS, method="POST").respond_with_handler(
        capture_upload(created(), 201, seen)
    )
    result = _client(httpserver, http).create(b"# Villa", filename="guidebook.md", name="Villa")
    assert result == CreatedDocument(document_id=DOCUMENT_ID, chunk_count=3)
    assert seen == [{"form": {"name": "Villa"}, "files": {"file": ("guidebook.md", b"# Villa")}}]


def test_replace_is_one_put_that_keeps_the_name_unless_given(
    httpserver: HTTPServer, http: httpx.Client
) -> None:
    seen: list[dict[str, Any]] = []
    httpserver.expect_request(DOCUMENT, method="PUT").respond_with_handler(
        capture_upload(created(5), 200, seen)
    )
    result = _client(httpserver, http).replace(DOCUMENT_ID, b"v2", filename="g.md", name=None)
    assert result.chunk_count == 5
    assert seen[0]["form"] == {}
    assert calls(httpserver) == [("PUT", DOCUMENT)]


def test_replace_sends_a_new_name(httpserver: HTTPServer, http: httpx.Client) -> None:
    seen: list[dict[str, Any]] = []
    httpserver.expect_request(DOCUMENT, method="PUT").respond_with_handler(
        capture_upload(created(), 200, seen)
    )
    _client(httpserver, http).replace(DOCUMENT_ID, b"v2", filename="g.md", name="New")
    assert seen[0]["form"] == {"name": "New"}


def test_search_sends_the_message_and_reads_the_chunks_in_order(
    httpserver: HTTPServer, http: httpx.Client
) -> None:
    httpserver.expect_request(SEARCH, method="POST", json={"query": "check-in?"}).respond_with_json(
        hits("Check-in 15:00", "Parking")
    )
    chunks = _client(httpserver, http).search(DOCUMENT_ID, "check-in?")
    assert [chunk.text for chunk in chunks] == ["Check-in 15:00", "Parking"]


def test_an_empty_search_is_an_empty_list(httpserver: HTTPServer, http: httpx.Client) -> None:
    httpserver.expect_request(SEARCH, method="POST").respond_with_json(hits())
    assert _client(httpserver, http).search(DOCUMENT_ID, "anything") == []


def test_delete_is_one_delete(httpserver: HTTPServer, http: httpx.Client) -> None:
    httpserver.expect_request(DOCUMENT, method="DELETE").respond_with_data("", status=204)
    _client(httpserver, http).delete(DOCUMENT_ID)
    assert calls(httpserver) == [("DELETE", DOCUMENT)]
