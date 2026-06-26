import anthropic
import httpx
import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import SecretStr

from application.exceptions import InvalidApiKeyError, UpstreamLLMError
from domain.entities.generated_reply import GeneratedReply
from domain.entities.guest_message import GuestMessage
from infrastructure.llm.anthropic_llm_client import AnthropicLLMClient, _build_chat
from tests._support.builders import make_chunk, make_guidebook_id


class _FakeChat:
    """Stand-in for ChatAnthropic: records messages, then returns a reply or raises an error."""

    def __init__(self, *, reply: BaseMessage | None = None, error: Exception | None = None) -> None:
        self._reply = reply
        self._error = error
        self.messages: list[BaseMessage] | None = None

    def invoke(self, messages: list[BaseMessage]) -> BaseMessage:
        self.messages = messages
        if self._error is not None:
            raise self._error
        assert self._reply is not None
        return self._reply


def _client(chat: _FakeChat, record: dict[str, object] | None = None) -> AnthropicLLMClient:
    def factory(
        model_id: str, api_key: SecretStr, base_url: str, timeout: float, max_tokens: int
    ) -> _FakeChat:
        if record is not None:
            record.update(model_id=model_id, api_key=api_key, base_url=base_url)
        return chat

    return AnthropicLLMClient(
        base_url="https://api.anthropic.com", timeout_seconds=5.0, chat_factory=factory
    )


def _gen(client: AnthropicLLMClient, *, is_byok: bool) -> GeneratedReply:
    return client.generate(
        chunks=[make_chunk(make_guidebook_id(), ordinal=0, text="ctx")],
        guest_message=GuestMessage.create("question?"),
        model_id="claude-haiku-4-5",
        system_prompt="sys",
        max_output_tokens=100,
        api_key=SecretStr("sk-test"),
        is_byok=is_byok,
    )


def _reply(text: str, output_tokens: int) -> AIMessage:
    return AIMessage(
        content=text,
        usage_metadata={
            "input_tokens": 1,
            "output_tokens": output_tokens,
            "total_tokens": output_tokens + 1,
        },
    )


def _status_error(cls: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


def test_build_chat_routes_key_through_x_api_key_field() -> None:
    # Constraint (b): the key must authenticate via x-api-key, never Authorization: Bearer. The
    # anthropic SDK uses x-api-key exclusively, so routing the key into ChatAnthropic's
    # ``anthropic_api_key`` field (not a hand-built header) guarantees it at the construction seam.
    chat = _build_chat("claude-haiku-4-5", SecretStr("sk-secret"), "https://api.anthropic.com", 5.0, 64)
    assert isinstance(chat, ChatAnthropic)
    assert chat.anthropic_api_key is not None
    assert chat.anthropic_api_key.get_secret_value() == "sk-secret"


def test_success_maps_text_and_output_tokens() -> None:
    reply = _gen(_client(_FakeChat(reply=_reply("answer", 12))), is_byok=True)
    assert reply.text == "answer" and reply.output_tokens == 12


def test_passes_key_model_and_builds_system_and_user_messages() -> None:
    record: dict[str, object] = {}
    chat = _FakeChat(reply=_reply("ok", 1))
    _gen(_client(chat, record), is_byok=True)
    assert record["model_id"] == "claude-haiku-4-5"
    key = record["api_key"]
    assert isinstance(key, SecretStr) and key.get_secret_value() == "sk-test"
    assert record["base_url"] == "https://api.anthropic.com"
    assert chat.messages is not None
    assert isinstance(chat.messages[0], SystemMessage)
    assert isinstance(chat.messages[1], HumanMessage)
    assert "ctx" in chat.messages[1].content
    assert "question?" in chat.messages[1].content


def test_byok_401_maps_to_invalid_api_key() -> None:
    chat = _FakeChat(error=_status_error(anthropic.AuthenticationError, 401))
    with pytest.raises(InvalidApiKeyError):
        _gen(_client(chat), is_byok=True)


def test_server_401_maps_to_non_retryable_upstream() -> None:
    chat = _FakeChat(error=_status_error(anthropic.AuthenticationError, 401))
    with pytest.raises(UpstreamLLMError) as exc:
        _gen(_client(chat), is_byok=False)
    assert exc.value.retryable is False and exc.value.upstream_status == 401


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retryable_upstream_statuses(status: int) -> None:
    cls = anthropic.RateLimitError if status == 429 else anthropic.APIStatusError
    chat = _FakeChat(error=_status_error(cls, status))
    with pytest.raises(UpstreamLLMError) as exc:
        _gen(_client(chat), is_byok=False)
    assert exc.value.retryable is True


def test_other_4xx_maps_to_non_retryable_upstream() -> None:
    chat = _FakeChat(error=_status_error(anthropic.APIStatusError, 400))
    with pytest.raises(UpstreamLLMError) as exc:
        _gen(_client(chat), is_byok=False)
    assert exc.value.retryable is False and exc.value.upstream_status == 400


def test_unexpected_response_type_maps_to_non_retryable_upstream() -> None:
    chat = _FakeChat(reply=HumanMessage(content="not an AIMessage"))
    with pytest.raises(UpstreamLLMError) as exc:
        _gen(_client(chat), is_byok=True)
    assert exc.value.retryable is False


def test_timeout_maps_to_retryable_upstream() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    chat = _FakeChat(error=anthropic.APITimeoutError(request=request))
    with pytest.raises(UpstreamLLMError) as exc:
        _gen(_client(chat), is_byok=True)
    assert exc.value.retryable is True
