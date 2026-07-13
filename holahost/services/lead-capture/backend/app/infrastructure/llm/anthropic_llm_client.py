from __future__ import annotations

from typing import TYPE_CHECKING

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from application.exceptions import InvalidApiKeyError, UpstreamLLMError
from domain.entities.chunk import Chunk
from domain.entities.generated_reply import GeneratedReply
from domain.entities.guest_message import GuestMessage

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import BaseMessage
    from pydantic import SecretStr

    # Builds the chat model for one call: (model_id, api_key, base_url, timeout_s, max_tokens).
    ChatFactory = Callable[[str, SecretStr, str, float, int], BaseChatModel]


def _build_chat(
    model_id: str,
    api_key: SecretStr,
    base_url: str,
    timeout_seconds: float,
    max_output_tokens: int,
) -> BaseChatModel:
    """Construct the production ``ChatAnthropic`` for one ``generate`` call (C-15).

    A fresh client per call lets the per-request key (server key or BYOK) flow in without being stored
    on the adapter. ``max_retries=0`` keeps a single attempt, so the ``retryable`` flag we map onto
    ``UpstreamLLMError`` stays meaningful (the caller owns retry policy, not the SDK).
    """
    return ChatAnthropic(
        model=model_id,
        anthropic_api_key=api_key,
        anthropic_api_url=base_url,
        max_tokens=max_output_tokens,
        default_request_timeout=timeout_seconds,
        max_retries=0,
    )


class AnthropicLLMClient:
    """LLMClient adapter over Anthropic via ``langchain_anthropic.ChatAnthropic`` (spec §10.3, C-15, D3).

    Wraps ``ChatAnthropic`` (which authenticates with ``x-api-key`` — C-02, verified) behind the
    LLMClient port. A fresh ``ChatAnthropic`` is built per call so the per-request key (server or BYOK)
    is never stored on the instance. Upstream failures surface as ``anthropic`` SDK exceptions and map
    by flow (D3): a BYOK 401 -> ``InvalidApiKeyError`` (-> 401); a server-key 401 -> ``UpstreamLLMError``
    retryable=False (-> 502); 429/5xx and timeout/connection errors -> retryable ``UpstreamLLMError``;
    other 4xx -> non-retryable. ``chat_factory`` is injected for tests (a fake chat model); production
    uses ``_build_chat``.

    Structurally conforms to the LLMClient port (no inheritance): see ``_conforms``.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        chat_factory: ChatFactory = _build_chat,
    ) -> None:
        """Init.

        Args:
            base_url: Anthropic API base, e.g. ``https://api.anthropic.com``.
            timeout_seconds: Per-request timeout.
            chat_factory: Builds the chat model per call (tests inject a fake; default ``_build_chat``).
        """
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._chat_factory = chat_factory

    def generate(
        self,
        chunks: list[Chunk],
        guest_message: GuestMessage,
        model_id: str,
        system_prompt: str,
        max_output_tokens: int,
        api_key: SecretStr,
        is_byok: bool,
    ) -> GeneratedReply:
        """Generate a reply grounded in ``chunks`` (see port; §8.2.4).

        :raises InvalidApiKeyError: upstream 401 on a BYOK key (§9.5 / §9.8).
        :raises UpstreamLLMError: upstream 429/5xx, timeout, or 401 on the server key (§9.1 / §9.8).
        """
        chat = self._chat_factory(
            model_id, api_key, self._base_url, self._timeout, max_output_tokens
        )
        messages: list[BaseMessage] = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=self._build_user_content(chunks, guest_message)),
        ]
        try:
            response = chat.invoke(messages)
        except anthropic.APIError as exc:
            raise self._map_error(exc, is_byok=is_byok) from exc
        # A chat model always replies with an AIMessage; a different type is an upstream contract
        # violation (not a transient fault), so it is non-retryable.
        if not isinstance(response, AIMessage):
            raise UpstreamLLMError(
                retryable=False, message=f"unexpected response type: {type(response).__name__}"
            )
        return GeneratedReply.create(
            text=response.text, output_tokens=self._output_tokens(response)
        )

    @staticmethod
    def _build_user_content(chunks: list[Chunk], guest_message: GuestMessage) -> str:
        context = "\n\n".join(chunk.text for chunk in chunks)
        return f"<context>\n{context}\n</context>\n\n{guest_message.text}"

    @staticmethod
    def _map_error(
        exc: anthropic.APIError, *, is_byok: bool
    ) -> InvalidApiKeyError | UpstreamLLMError:
        if isinstance(exc, anthropic.AuthenticationError):
            if is_byok:
                return InvalidApiKeyError()
            return UpstreamLLMError(retryable=False, upstream_status=401)
        if isinstance(exc, anthropic.RateLimitError):
            return UpstreamLLMError(retryable=True, upstream_status=429)
        if isinstance(exc, anthropic.APIStatusError):
            return UpstreamLLMError(
                retryable=exc.status_code >= 500, upstream_status=exc.status_code
            )
        # APIConnectionError / APITimeoutError and any other transport-level SDK error.
        return UpstreamLLMError(retryable=True, message=str(exc))

    @staticmethod
    def _output_tokens(response: AIMessage) -> int:
        if response.usage_metadata is None:
            return 0
        return int(response.usage_metadata["output_tokens"])


if TYPE_CHECKING:
    from application.ports.llm import LLMClient

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: AnthropicLLMClient) -> LLMClient:
        return x
