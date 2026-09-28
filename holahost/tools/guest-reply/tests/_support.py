"""Both services faked on one local HTTP server: their paths never overlap, so one plays both."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr
from pytest_httpserver import HTTPServer
from werkzeug import Request, Response

from guest_reply import flows
from guest_reply.clients import documents, generation
from guest_reply.clients.auth import StaticToken
from guest_reply.clients.http import ServiceCaller

TOKEN = "header.payload.signature"
REQUEST_ID = "req-test-1"
DOCUMENT_ID = "3f0c5a2e-8d4b-4c1a-9e7f-2b6d1c0a9e11"
DOCUMENTS = "/api/rag-documents/documents"
DOCUMENT = f"{DOCUMENTS}/{DOCUMENT_ID}"
SEARCH = f"{DOCUMENT}/search"
GENERATE = "/api/llm-client/generate"


def origin(httpserver: HTTPServer) -> str:
    return httpserver.url_for("/").rstrip("/")


def envelope(code: str, message: str = "", details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def created(chunk_count: int = 3) -> dict[str, Any]:
    return {
        "document_id": DOCUMENT_ID,
        "name": "guidebook.md",
        "mime_type": "text/markdown",
        "chunk_count": chunk_count,
        "created_at": "2026-09-28T12:00:00Z",
        "updated_at": "2026-09-28T12:00:00Z",
    }


def hits(*texts: str) -> dict[str, Any]:
    return {
        "chunks": [
            {"chunk_id": f"c{number}", "text": text, "page": None, "score": 0.9 - number / 10}
            for number, text in enumerate(texts)
        ]
    }


def generated(text: str = "Check-in is from 15:00.") -> dict[str, Any]:
    return {
        "text": text,
        "usage": {"input_tokens": 120, "output_tokens": 12},
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "finish_reason": "stop",
        "downgraded": False,
        "failed_over": False,
    }


def capture_upload(
    body: dict[str, Any], status: int, seen: list[dict[str, Any]]
) -> Callable[[Request], Response]:
    """A handler that records a multipart upload's form and files while the request is open."""

    def handler(request: Request) -> Response:
        seen.append(
            {
                "form": request.form.to_dict(),
                "files": {
                    name: (upload.filename, upload.read()) for name, upload in request.files.items()
                },
            }
        )
        return Response(json.dumps(body), status=status, content_type="application/json")

    return handler


def caller(
    httpserver: HTTPServer, http: httpx.Client, api_base: str, *, waits: list[int] | None = None
) -> ServiceCaller:
    recorded = waits if waits is not None else []
    return ServiceCaller(
        http,
        origin=origin(httpserver),
        api_base=api_base,
        token=StaticToken(SecretStr(TOKEN)),
        request_id=REQUEST_ID,
        on_wait=recorded.append,
        sleep=lambda _seconds: None,
    )


def services(httpserver: HTTPServer, http: httpx.Client) -> flows.Services:
    return flows.Services(
        documents=documents.DocumentsClient(caller(httpserver, http, documents.API_BASE)),
        generation=generation.GenerationClient(caller(httpserver, http, generation.API_BASE)),
        model_alias="fast",
    )


def calls(httpserver: HTTPServer) -> list[tuple[str, str]]:
    """The calls the fake received, in order."""
    return [(request.method, request.path) for request, _ in httpserver.log]
