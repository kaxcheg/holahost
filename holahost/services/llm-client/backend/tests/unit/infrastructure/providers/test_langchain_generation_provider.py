"""`LangchainGenerationProvider` with the Anthropic dialect, against a local fake of the vendor's
API.

The real SDK and the real langchain integration run end to end — only the vendor's HTTP endpoint is
faked — so what these tests pin is the translation the adapter exists for: statuses into the port's
errors, stop reasons into `FinishReason`, the vendor's figures into `Usage`.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import anthropic
import pytest
from pydantic import SecretStr
from pytest_httpserver import HTTPServer
from tests._support.builders import HAIKU, make_usage
from tests._support.registry import registry_data
from werkzeug import Request, Response

from application.ports.exceptions import (
    ProviderRefusedContentError,
    ProviderRejectedRequestError,
    TransientProviderError,
)
from application.ports.generation import Generation
from config.logging import configure_logging
from config.registry import RegistryFile
from domain.value_objects.finish_reason import FinishReason
from domain.value_objects.message import Message
from domain.value_objects.role import Role
from infrastructure.providers.langchain_generation_provider import (
    LangchainGenerationProvider,
    build_generation_provider,
)

_MESSAGES = "/v1/messages"


def _provider(httpserver: HTTPServer) -> LangchainGenerationProvider:
    data = registry_data()
    data["providers"]["other-vendor"]["enabled"] = False  # no dialect of its own
    return build_generation_provider(
        RegistryFile.model_validate(data),
        {"anthropic": SecretStr("sk-test")},
        base_url=httpserver.url_for("/").rstrip("/"),
    )


def _generate(
    provider: LangchainGenerationProvider,
    *,
    system: str = "You answer guests.",
    temperature: float | None = None,
    stop: list[str] | None = None,
    timeout_s: float = 5.0,
) -> Generation:
    return provider.generate(
        HAIKU,
        system=system,
        messages=[Message(role=Role.USER, text="What time is check-in?")],
        max_tokens=100,
        temperature=temperature,
        stop=stop,
        timeout_s=timeout_s,
        request_id="req-1",
    )


def _answer(
    *, stop_reason: str = "end_turn", input_tokens: int = 12, output_tokens: int = 7
) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5",
        "content": [{"type": "text", "text": "Check-in is from 15:00."}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


def _error(kind: str) -> dict[str, Any]:
    return {"type": "error", "error": {"type": kind, "message": "from the fake vendor"}}


def _sent(httpserver: HTTPServer) -> dict[str, Any]:
    [(request, _)] = httpserver.log
    body: dict[str, Any] = json.loads(request.data)
    return body


class TestAnAnswer:
    def test_the_text_and_the_vendors_figures_are_returned(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request(_MESSAGES, method="POST").respond_with_json(_answer())
        generation = _generate(_provider(httpserver))
        assert generation == Generation(
            text="Check-in is from 15:00.", usage=make_usage(12, 7), finish_reason=FinishReason.STOP
        )
        assert type(generation.text) is str

    def test_the_request_carries_what_the_caller_sent(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request(_MESSAGES, method="POST").respond_with_json(_answer())

        _generate(_provider(httpserver), temperature=0.3, stop=["\n\n"])

        body = _sent(httpserver)
        assert body["model"] == "claude-haiku-4-5"
        assert (body["max_tokens"], body["temperature"], body["stop_sequences"]) == (
            100,
            0.3,
            ["\n\n"],
        )
        assert "You answer guests." in json.dumps(body["system"])
        assert [message["role"] for message in body["messages"]] == ["user"]
        assert "What time is check-in?" in json.dumps(body["messages"])
        assert httpserver.log[0][0].headers["x-api-key"] == "sk-test"

    def test_an_empty_system_sends_no_system_block(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request(_MESSAGES, method="POST").respond_with_json(_answer())
        _generate(_provider(httpserver), system="")
        assert "system" not in _sent(httpserver)

    def test_an_unset_temperature_is_left_to_the_vendor(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request(_MESSAGES, method="POST").respond_with_json(_answer())
        _generate(_provider(httpserver), temperature=None)
        assert "temperature" not in _sent(httpserver)

    @pytest.mark.parametrize(
        ("stop_reason", "finish"),
        [("max_tokens", FinishReason.MAX_TOKENS), ("stop_sequence", FinishReason.STOP)],
    )
    def test_the_stop_reason_is_read(
        self, httpserver: HTTPServer, stop_reason: str, finish: FinishReason
    ) -> None:
        httpserver.expect_request(_MESSAGES).respond_with_json(_answer(stop_reason=stop_reason))
        assert _generate(_provider(httpserver)).finish_reason is finish

    def test_a_refusal_carries_the_usage(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request(_MESSAGES).respond_with_json(
            _answer(stop_reason="refusal", input_tokens=5, output_tokens=0)
        )
        with pytest.raises(ProviderRefusedContentError) as exc:
            _generate(_provider(httpserver))
        assert exc.value.usage == make_usage(5, 0)

    def test_an_unmapped_stop_reason_is_a_stop_and_is_logged(
        self, httpserver: HTTPServer, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging()
        httpserver.expect_request(_MESSAGES).respond_with_json(_answer(stop_reason="pause_turn"))

        assert _generate(_provider(httpserver)).finish_reason is FinishReason.STOP

        line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert (line["event"], line["vendor_stop_reason"], line["request_id"]) == (
            "vendor_stop_reason_unmapped",
            "pause_turn",
            "req-1",
        )

    def test_an_answer_without_usage_is_rejected(self, httpserver: HTTPServer) -> None:
        answer = _answer()
        del answer["usage"]
        httpserver.expect_request(_MESSAGES).respond_with_json(answer)
        with pytest.raises(ProviderRejectedRequestError):
            _generate(_provider(httpserver))


class TestVendorErrors:
    @pytest.mark.parametrize(
        ("status", "kind"),
        [(429, "rate_limit_error"), (500, "api_error"), (529, "overloaded_error")],
    )
    def test_a_transient_status_is_worth_repeating(
        self, httpserver: HTTPServer, status: int, kind: str
    ) -> None:
        httpserver.expect_request(_MESSAGES).respond_with_json(_error(kind), status=status)
        with pytest.raises(TransientProviderError) as exc:
            _generate(_provider(httpserver))
        assert (exc.value.status, exc.value.retry_after) == (status, None)

    def test_retry_after_in_seconds_is_passed_on(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request(_MESSAGES).respond_with_json(
            _error("rate_limit_error"), status=429, headers={"retry-after": "3"}
        )
        with pytest.raises(TransientProviderError) as exc:
            _generate(_provider(httpserver))
        assert exc.value.retry_after == 3.0

    def test_retry_after_as_a_date_is_left_to_the_backoff(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request(_MESSAGES).respond_with_json(
            _error("rate_limit_error"),
            status=429,
            headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"},
        )
        with pytest.raises(TransientProviderError) as exc:
            _generate(_provider(httpserver))
        assert exc.value.retry_after is None

    @pytest.mark.parametrize(
        ("status", "kind"),
        [
            (400, "invalid_request_error"),
            (401, "authentication_error"),
            (403, "permission_error"),
            (404, "not_found_error"),
        ],
    )
    def test_a_rejected_request_names_its_status(
        self, httpserver: HTTPServer, status: int, kind: str
    ) -> None:
        httpserver.expect_request(_MESSAGES).respond_with_json(_error(kind), status=status)
        with pytest.raises(ProviderRejectedRequestError) as exc:
            _generate(_provider(httpserver))
        assert exc.value.status == status

    def test_the_vendors_account_is_kept_for_the_log(self, httpserver: HTTPServer) -> None:
        # A rejection by every candidate is answered `500`, and this message is all the log keeps.
        httpserver.expect_request(_MESSAGES).respond_with_json(
            _error("not_found_error"), status=404, headers={"request-id": "req_vendor_1"}
        )
        with pytest.raises(ProviderRejectedRequestError) as exc:
            _generate(_provider(httpserver))
        assert str(exc.value).endswith(
            "(404) not_found_error: from the fake vendor [request-id req_vendor_1]"
        )

    def test_a_body_that_is_not_the_vendors_is_left_out(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request(_MESSAGES).respond_with_data(
            "<html>502 Bad Gateway</html>", status=502, content_type="text/html"
        )
        with pytest.raises(TransientProviderError) as exc:
            _generate(_provider(httpserver))
        assert str(exc.value).endswith("(502)")

    def test_a_timeout_is_transient_without_a_status(self, httpserver: HTTPServer) -> None:
        release = threading.Event()

        def slow(request: Request) -> Response:
            del request
            release.wait(timeout=5.0)
            return Response(json.dumps(_answer()), content_type="application/json")

        httpserver.expect_request(_MESSAGES).respond_with_handler(slow)
        try:
            with pytest.raises(TransientProviderError) as exc:
                _generate(_provider(httpserver), timeout_s=0.2)
            assert exc.value.status is None
        finally:
            # The abandoned request is finished here, pass or fail: the server shared by the tests
            # would otherwise log it in the next one's exchange.
            release.set()
            deadline = time.monotonic() + 5.0
            while not httpserver.log and time.monotonic() < deadline:
                time.sleep(0.01)

    def test_the_attempts_time_is_the_answers(
        self, httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Read off the request the SDK hands its HTTP client: the bounds that client enforces.
        enforced: list[object] = []
        send = anthropic.DefaultHttpxClient.send

        def recording(client: anthropic.DefaultHttpxClient, request: Any, **kwargs: Any) -> Any:
            enforced.append(request.extensions["timeout"])
            return send(client, request, **kwargs)

        monkeypatch.setattr(anthropic.DefaultHttpxClient, "send", recording)
        httpserver.expect_request(_MESSAGES).respond_with_json(_answer())

        _generate(_provider(httpserver), timeout_s=20.0)

        assert enforced == [{"connect": 1.0, "read": 20.0, "write": 1.0, "pool": 1.0}]

    def test_the_sdk_does_not_repeat_on_its_own(self, httpserver: HTTPServer) -> None:
        httpserver.expect_request(_MESSAGES).respond_with_json(
            _error("overloaded_error"), status=529
        )
        with pytest.raises(TransientProviderError):
            _generate(_provider(httpserver))
        assert len(httpserver.log) == 1
