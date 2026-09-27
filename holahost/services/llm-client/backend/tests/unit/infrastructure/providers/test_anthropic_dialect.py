"""The Anthropic dialect's own rules, apart from any HTTP exchange."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from application.ports.exceptions import ProviderRejectedRequestError
from domain.value_objects.finish_reason import FinishReason
from infrastructure.providers.anthropic_dialect import AnthropicDialect
from infrastructure.providers.dialects import DIALECTS


class TestStopReasons:
    @pytest.mark.parametrize(
        ("stop_reason", "finish"),
        [
            ("end_turn", FinishReason.STOP),
            ("stop_sequence", FinishReason.STOP),
            ("max_tokens", FinishReason.MAX_TOKENS),
            ("model_context_window_exceeded", FinishReason.MAX_TOKENS),
        ],
    )
    def test_the_table(self, stop_reason: str, finish: FinishReason) -> None:
        assert AnthropicDialect().finish_reason(stop_reason) is finish

    @pytest.mark.parametrize("stop_reason", ["tool_use", "pause_turn", "refusal", None])
    def test_outside_the_table_is_none(self, stop_reason: str | None) -> None:
        assert AnthropicDialect().finish_reason(stop_reason) is None

    def test_a_refusal_is_told_apart(self) -> None:
        assert AnthropicDialect().is_refusal("refusal")
        assert not AnthropicDialect().is_refusal("end_turn")


class TestTheEndpoint:
    @pytest.mark.parametrize(
        "variable", ["ANTHROPIC_API_URL", "ANTHROPIC_BASE_URL", "LANGSMITH_GATEWAY"]
    )
    def test_the_environment_cannot_redirect_the_calls(
        self, monkeypatch: pytest.MonkeyPatch, variable: str
    ) -> None:
        # Prompts and the provider key go where the service says, not where a stray variable does.
        monkeypatch.setenv(variable, "https://elsewhere.example")
        model = AnthropicDialect().chat_model(
            "claude-haiku-4-5", SecretStr("sk-test"), base_url=None
        )
        assert model.anthropic_api_url == "https://api.anthropic.com"

    def test_an_explicit_endpoint_is_used(self) -> None:
        model = AnthropicDialect().chat_model(
            "claude-haiku-4-5", SecretStr("sk-test"), base_url="http://127.0.0.1:9"
        )
        assert model.anthropic_api_url == "http://127.0.0.1:9"


class TestTheTimeout:
    def test_the_answer_gets_the_whole_attempt_and_the_setup_a_second(self) -> None:
        assert AnthropicDialect().timeout(20.0).as_dict() == {
            "connect": 1.0,
            "read": 20.0,
            "write": 1.0,
            "pool": 1.0,
        }

    def test_the_setup_never_gets_more_than_the_attempt(self) -> None:
        assert set(AnthropicDialect().timeout(0.5).as_dict().values()) == {0.5}


class TestUsage:
    def test_is_reported_when_the_vendor_sent_it(self) -> None:
        metadata = {"usage": {"input_tokens": 12, "output_tokens": 7}}
        assert AnthropicDialect().reports_usage(metadata)

    def test_is_not_when_it_is_absent(self) -> None:
        # langchain still fills `usage_metadata` with zeros, which would pass for confirmed spend.
        assert not AnthropicDialect().reports_usage({"usage": None})
        assert not AnthropicDialect().reports_usage({})


class TestErrors:
    def test_anything_but_a_vendor_error_is_a_rejection_without_a_status(self) -> None:
        error = AnthropicDialect().translate(KeyError("content"))
        assert isinstance(error, ProviderRejectedRequestError)
        assert error.status is None


class TestTheRegister:
    def test_anthropic_has_a_dialect(self) -> None:
        assert isinstance(DIALECTS["anthropic"], AnthropicDialect)
