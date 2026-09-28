"""`llm-client`: one generation, with the alias the tool is configured with."""

from __future__ import annotations

import json

import httpx
from pytest_httpserver import HTTPServer

from guest_reply.clients.generation import API_BASE, GenerationClient, Message, Usage
from tests._support import GENERATE, caller, generated


def test_generate_sends_the_prompt_and_the_alias_and_reads_the_answer(
    httpserver: HTTPServer, http: httpx.Client
) -> None:
    httpserver.expect_request(GENERATE, method="POST").respond_with_json(generated())
    client = GenerationClient(caller(httpserver, http, API_BASE))

    result = client.generate(
        system="You are the host.", messages=[Message(role="user", content="Hi")], model="fast"
    )

    assert result.text == "Check-in is from 15:00."
    assert (result.provider, result.model) == ("anthropic", "claude-haiku-4-5")
    assert result.usage == Usage(input_tokens=120, output_tokens=12)
    request, _ = httpserver.log[0]
    assert json.loads(request.data) == {
        "model": "fast",
        "system": "You are the host.",
        "messages": [{"role": "user", "content": "Hi"}],
    }
