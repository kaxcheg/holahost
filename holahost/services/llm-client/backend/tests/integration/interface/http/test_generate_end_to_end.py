"""`POST /generate` through the real composition root: the edge, the use case and Postgres.

Only the vendor is scripted — no test reaches a real provider. Everything between the socket and
the provider port is the application `scripts/bootstrap.py` builds: authentication with a token
signed by a key fetched over HTTP, the rate limiter, the per-request unit of work, the budget
aggregates and the usage write.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from holahost_db import SqlAlchemyUnitOfWork
from sqlalchemy import text
from tests._support.builders import HAIKU, make_generation, make_usage
from tests._support.fakes import FakeClock, ScriptedGenerationProvider
from tests._support.generate import ok

from application.limits import MAX_INPUT_BYTES
from interface.http.api_base import API_BASE_URL
from interface.http.dependencies import get_generation_provider

pytestmark = pytest.mark.integration

_URL = f"{API_BASE_URL}/generate"
_BODY = {
    "model": "fast",
    "system": "You answer guests.",
    "messages": [{"role": "user", "content": "What time is check-in?"}],
}


@pytest.fixture
def provider(client: TestClient) -> Iterator[ScriptedGenerationProvider]:
    answer = make_generation(text="From 15:00.", usage=make_usage(120, 8))
    scripted = ScriptedGenerationProvider(
        FakeClock(), {HAIKU.id.value: [ok(generation=answer), ok(generation=answer)]}
    )
    app = client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[get_generation_provider] = lambda: scripted
    yield scripted
    app.dependency_overrides.pop(get_generation_provider, None)


def _usage_rows(uow: SqlAlchemyUnitOfWork) -> list[tuple[str, str, int, int]]:
    with uow:
        rows = uow.connection().execute(
            text("SELECT request_id, model, input_tokens, output_tokens FROM usage_records")
        )
        return [(row[0], row[1], row[2], row[3]) for row in rows]


class TestGeneration:
    def test_answers_and_records_the_spend(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        provider: ScriptedGenerationProvider,
        uow: SqlAlchemyUnitOfWork,
    ) -> None:
        response = client.post(_URL, json=_BODY, headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["text"] == "From 15:00."
        assert response.json()["model"] == "claude-haiku-4-5"
        assert _usage_rows(uow) == [("e2e-test-request-id", "claude-haiku-4-5", 120, 8)]

    def test_a_repeated_key_is_refused_without_paying_twice(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        provider: ScriptedGenerationProvider,
        uow: SqlAlchemyUnitOfWork,
    ) -> None:
        headers = {**auth_headers, "Idempotency-Key": "e2e-key-1"}

        first = client.post(_URL, json=_BODY, headers=headers)
        repeat = client.post(_URL, json=_BODY, headers=headers)

        assert first.status_code == 200
        assert repeat.status_code == 409
        assert repeat.json()["error"]["details"] == {"state": "completed"}
        assert len(provider.calls) == 1
        assert len(_usage_rows(uow)) == 1

    def test_a_body_past_the_input_ceiling_is_refused_unread(
        self, client: TestClient, auth_headers: dict[str, str], provider: ScriptedGenerationProvider
    ) -> None:
        oversized = {**_BODY, "system": "x" * MAX_INPUT_BYTES}

        response = client.post(_URL, json=oversized, headers=auth_headers)

        assert response.status_code == 413
        assert provider.calls == []

    def test_generation_needs_a_token(
        self, client: TestClient, provider: ScriptedGenerationProvider
    ) -> None:
        response = client.post(_URL, json=_BODY, headers={"X-Request-ID": "e2e-no-token"})

        assert response.status_code == 401
        assert provider.calls == []
