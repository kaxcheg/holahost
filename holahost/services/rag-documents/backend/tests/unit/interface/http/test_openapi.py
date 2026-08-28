"""The generated document has to describe the whole of *this service's* contract.

FastAPI's generator reads a route's signature and nothing else — not exception handlers,
not middleware. So everything a caller must send or may receive has to be stated in the
signature, or it is simply absent from `docs/openapi.json`. Before it was: the document
promised FastAPI's own `HTTPValidationError` body for 422, a shape this service never
returns, and mentioned no other failure at all.

What it deliberately does *not* describe is the platform's half — `401`/`503`, `429`, and
the transport `413`. Those come from the shared edge, are identical behind every service,
and belong to the platform contract; restating them per service would make one fact look
like N. That exclusion is pinned here too, so it stays a decision rather than an
omission.
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
from interface.http.router import router as documents_router

_COMMITTED = Path(__file__).resolve().parents[5] / "docs" / "openapi.json"
_PLATFORM_STATUSES = {"401", "403", "429", "503"}


def _document() -> dict[str, Any]:
    # Routers only — `create_app()` would need real settings, and nothing asserted here
    # depends on the middleware stack being built. That is the point: the schema comes
    # out of the route signatures, so the routers alone produce all of it.
    app = FastAPI()
    app.include_router(health_router, prefix=API_BASE_URL)
    app.include_router(documents_router, prefix=API_BASE_URL)
    return app.openapi()


def _guarded(schema: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (f"{verb} {path}", operation)
        for path, operations in schema["paths"].items()
        if path != HEALTH_PATH
        for verb, operation in operations.items()
    ]


class TestWhatACallerMustSend:
    def test_every_guarded_operation_requires_the_bearer_token(self) -> None:
        schema = _document()
        assert "bearerAuth" in schema["components"]["securitySchemes"]
        for name, operation in _guarded(schema):
            assert operation["security"] == [{"bearerAuth": []}], name

    def test_no_operation_publishes_the_request_id_header(self) -> None:
        # Required of every guarded route and deliberately undocumented — see the comment
        # on `router`. It is not the caller's to send, and naming it would hand the one
        # caller who could be missing it the hint `MalformedRequestError` withholds.
        # Pinned as a decision: it was published once, which is what this now prevents.
        for name, operation in _guarded(_document()):
            headers = {p["name"] for p in operation.get("parameters", []) if p["in"] == "header"}
            assert "X-Request-ID" not in headers, name

    def test_health_asks_for_neither(self) -> None:
        operation = _document()["paths"][HEALTH_PATH]["get"]
        assert "security" not in operation
        assert operation.get("parameters", []) == []


class TestWhatACallerMayReceive:
    def test_no_operation_declares_a_platform_answer(self) -> None:
        for name, operation in _guarded(_document()):
            assert _PLATFORM_STATUSES.isdisjoint(operation["responses"]), name

    def test_every_error_in_the_contract_is_described(self) -> None:
        # Read from the committed file, not a fresh render: `make openapi-check` proves
        # the file matches the code, and this proves the code publishes what it promises.
        published = json.loads(_COMMITTED.read_text())
        described = {
            code["const"]
            for schema in published["components"]["schemas"].values()
            for code in [schema.get("properties", {}).get("code", {})]
            if "const" in code
        }

        # Two additions to `ERROR_CONTRACT`, each for the same reason: nothing derives
        # them, so nothing but this line would notice them leaving the document.
        #
        # `MalformedRequestError` has no row in the table because `RequestIdMiddleware`
        # answers with it before routing (see `error_schemas`), yet a caller does receive
        # it — drop its model from the three unions and, without this, every test still
        # passes while the document stops describing a 422 the service really returns.
        #
        # `InternalError` is written out because it is the one identity with no class
        # behind it; an out-of-contract answer is still an answer, and its body needs a
        # schema like any other.
        expected = (
            {error.__name__ for error in ERROR_CONTRACT}
            | {MalformedRequestError.__name__}
            | {"InternalError"}
        )
        assert expected <= described

    def test_the_422_body_is_this_services_shape_not_fastapis(self) -> None:
        # Without explicit `responses`, FastAPI documents its own `HTTPValidationError`
        # for 422 — a `{"detail": [...]}` the service never returns, because
        # `handle_validation_error` overrides it.
        published = json.loads(_COMMITTED.read_text())
        assert "HTTPValidationError" not in published["components"]["schemas"]
        for name, operation in _guarded(published):
            ref = operation["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("ErrorResponse"), name
