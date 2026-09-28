"""`POST /generate` on a routes-only app: the use case runs over fakes, authentication is a stub.

The middleware stack and its order are the edge's and are exercised end to end in
`tests/integration/interface/http`; what is asserted here is the route's own work — the command it
builds, the response it maps, and the completion event it writes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from holahost_auth import TokenContext
from holahost_http import RequestIdMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from tests._support.builders import CLIENT, HAIKU, exhausted_budget, make_generation, make_usage
from tests._support.generate import Harness, build_use_case, ok
from tests._support.http import register_test_handlers

from config.logging import configure_logging
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from interface.http.api_base import API_BASE_URL
from interface.http.dependencies import get_generate_use_case
from interface.http.router import router

_URL = f"{API_BASE_URL}/generate"
_HEADERS = {"X-Request-ID": "req-42"}
_TOKEN = TokenContext(subject=CLIENT, client_id=CLIENT, roles=(), act=None)


def _body(**fields: object) -> dict[str, object]:
    body: dict[str, object] = {
        "model": "fast",
        "system": "You answer guests.",
        "messages": [{"role": "user", "content": "What time is check-in?"}],
    }
    return {**body, **fields}


class _StubAuthMiddleware:
    """Stands in for `HolahostAuthMiddleware`: writes the token where the real one does, which is
    where `current_token` and the completion event both read it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope.setdefault("state", {})["token"] = _TOKEN
        await self.app(scope, receive, send)


def _client(harness: Harness) -> TestClient:
    configure_logging()
    app = FastAPI()
    # Added innermost first: the request id is outermost, as `create_edge_app` orders them.
    app.add_middleware(_StubAuthMiddleware)
    app.add_middleware(RequestIdMiddleware)
    register_test_handlers(app)
    app.include_router(router, prefix=API_BASE_URL)
    app.dependency_overrides[get_generate_use_case] = lambda: harness.use_case
    return TestClient(app)


def _events(captured: str) -> list[dict[str, Any]]:
    lines = [json.loads(line) for line in captured.strip().splitlines() if line.startswith("{")]
    return [line for line in lines if line.get("event") == "op_completed"]


class TestTheAnswer:
    def test_generation_answers_with_the_model_that_answered_and_its_usage(self) -> None:
        answer = make_generation(text="From 15:00.", usage=make_usage(120, 8))
        h = build_use_case(script={HAIKU.id.value: [ok(generation=answer)]})

        response = _client(h).post(_URL, json=_body(), headers=_HEADERS)

        assert response.status_code == 200
        assert response.json() == {
            "text": "From 15:00.",
            "usage": {"input_tokens": 120, "output_tokens": 8},
            "provider": "anthropic",
            "model": "claude-haiku-4-5",
            "finish_reason": "stop",
            "downgraded": False,
            "failed_over": False,
        }

    def test_the_request_reaches_the_provider_as_it_was_sent(self) -> None:
        h = build_use_case()

        _client(h).post(
            _URL,
            json=_body(max_tokens=300, temperature=0.2, stop=["\n\n"]),
            headers=_HEADERS,
        )

        [call] = h.generation.calls
        assert call.system == "You answer guests."
        assert [message.text for message in call.messages] == ["What time is check-in?"]
        assert (call.max_tokens, call.temperature, call.stop) == (300, 0.2, ["\n\n"])
        assert call.request_id == "req-42"


class TestTheCommand:
    def test_the_caller_is_the_token_s_never_the_body_s(self) -> None:
        h = build_use_case()

        _client(h).post(_URL, json=_body(), headers={**_HEADERS, "Idempotency-Key": "k-1"})

        assert h.idempotency.begun == [(CLIENT, "k-1")]
        [record] = h.usage.added
        assert record.client_id == ClientId(CLIENT)

    def test_without_the_header_no_key_is_claimed(self) -> None:
        h = build_use_case()

        _client(h).post(_URL, json=_body(), headers=_HEADERS)

        assert h.idempotency.begun == []

    def test_a_key_past_its_limit_is_refused_by_the_use_case(self) -> None:
        h = build_use_case()

        response = _client(h).post(
            _URL, json=_body(), headers={**_HEADERS, "Idempotency-Key": "k" * 129}
        )

        assert response.status_code == 422
        assert response.json()["error"]["details"] == {"field": "idempotency_key", "limit": 128}


class TestTheCompletionEvent:
    def test_success_writes_one_event_with_the_service_s_fields(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        h = build_use_case()

        _client(h).post(_URL, json=_body(), headers=_HEADERS)

        [event] = _events(capsys.readouterr().out)
        assert event["route"] == f"POST {_URL}"
        assert event["outcome"] == "success"
        assert (event["request_id"], event["client_id"], event["sub"]) == ("req-42", CLIENT, CLIENT)
        assert event["requested_model"] == "fast"
        assert (event["provider"], event["model"]) == ("anthropic", "claude-haiku-4-5")
        assert (event["attempts"], event["provider_timeouts"]) == (1, 0)
        assert (event["downgraded"], event["failed_over"]) == (False, False)
        assert event["provider_ms"] == 1000
        assert "text" not in event

    def test_a_refusal_carries_what_was_asked_for(self, capsys: pytest.CaptureFixture[str]) -> None:
        h = build_use_case()

        response = _client(h).post(_URL, json=_body(model="huge"), headers=_HEADERS)

        [event] = _events(capsys.readouterr().out)
        assert response.status_code == 400
        assert (event["outcome"], event["requested_model"]) == ("UnknownModelError", "huge")


class TestBudgetRefusal:
    def test_answers_429_with_the_seconds_until_the_window_resets(self) -> None:
        h = build_use_case(budgets=[exhausted_budget(BudgetScope.CLIENT, ClientId(CLIENT))])

        response = _client(h).post(_URL, json=_body(), headers=_HEADERS)

        assert response.status_code == 429
        assert response.json()["error"]["details"]["scope"] == "client"
        assert int(response.headers["Retry-After"]) >= 1
