"""The generated document has to describe the whole of *this service's* contract.

FastAPI's generator reads a route's signature and nothing else — not exception handlers, not
middleware. So everything a caller must send or may receive has to be stated in the signature, or
it is absent from `docs/openapi.json`.

What it deliberately does *not* describe is the platform's half — `401`/`503`, the rate limiter's
`429`, the transport `413`: they come from the shared edge and are identical behind every service.
This service's own `429` — the budget — is described, with the `Retry-After` it owes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from application.exceptions import MalformedRequestError
from interface.http.api_base import API_BASE_URL
from interface.http.edge import HEALTH_PATH
from interface.http.errors import ERROR_CONTRACT
from interface.http.health import router as health_router
from interface.http.router import router as generation_router

_COMMITTED = Path(__file__).resolve().parents[5] / "docs" / "openapi.json"
_GENERATE = f"{API_BASE_URL}/generate"
_PLATFORM_STATUSES = {"401", "403", "413", "503"}


def _document() -> dict[str, Any]:
    # Routers only — `create_app()` would need real settings, and the schema comes out of the
    # route signatures, so the routers alone produce all of it.
    app = FastAPI()
    app.include_router(health_router, prefix=API_BASE_URL)
    app.include_router(generation_router, prefix=API_BASE_URL)
    return app.openapi()


def _generate(schema: dict[str, Any]) -> dict[str, Any]:
    operation: dict[str, Any] = schema["paths"][_GENERATE]["post"]
    return operation


class TestWhatACallerMustSend:
    def test_generation_requires_the_bearer_token(self) -> None:
        schema = _document()
        assert "bearerAuth" in schema["components"]["securitySchemes"]
        assert _generate(schema)["security"] == [{"bearerAuth": []}]

    def test_the_idempotency_key_is_an_optional_documented_header(self) -> None:
        headers = {
            p["name"]: p for p in _generate(_document())["parameters"] if p["in"] == "header"
        }
        assert headers["Idempotency-Key"]["required"] is False
        assert "128" in headers["Idempotency-Key"]["description"]

    def test_the_request_id_header_is_not_published(self) -> None:
        # Required and deliberately undocumented — see the comment on `router`.
        headers = {p["name"] for p in _generate(_document())["parameters"] if p["in"] == "header"}
        assert "X-Request-ID" not in headers

    def test_health_asks_for_neither(self) -> None:
        operation = _document()["paths"][HEALTH_PATH]["get"]
        assert "security" not in operation
        assert operation.get("parameters", []) == []


class TestWhatACallerMayReceive:
    def test_no_platform_answer_is_restated(self) -> None:
        assert _PLATFORM_STATUSES.isdisjoint(_generate(_document())["responses"])

    def test_the_budget_refusal_documents_retry_after(self) -> None:
        response = _generate(_document())["responses"]["429"]
        assert response["headers"]["Retry-After"]["schema"]["type"] == "integer"

    def test_every_error_in_the_contract_is_described(self) -> None:
        # Read from the committed file, not a fresh render: `make openapi-check` proves the file
        # matches the code, and this proves the code publishes what it promises.
        published = json.loads(_COMMITTED.read_text())
        described = {
            code["const"]
            for schema in published["components"]["schemas"].values()
            for code in [schema.get("properties", {}).get("code", {})]
            if "const" in code
        }
        # `MalformedRequestError` is answered before routing, so it has no row in the table yet a
        # caller receives it; `InternalError` has no class behind it. Nothing derives either.
        expected = (
            {error.__name__ for error in ERROR_CONTRACT}
            | {MalformedRequestError.__name__}
            | {"InternalError"}
        )
        assert expected <= described

    def test_the_422_body_is_this_service_s_shape_not_fastapi_s(self) -> None:
        published = json.loads(_COMMITTED.read_text())
        assert "HTTPValidationError" not in published["components"]["schemas"]
        schema = _generate(published)["responses"]["422"]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/GenerateRejectedResponse")
