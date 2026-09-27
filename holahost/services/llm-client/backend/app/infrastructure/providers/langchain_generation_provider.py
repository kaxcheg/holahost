"""`GenerationProvider` over langchain chat models."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import SecretStr

from application.ports.exceptions import ProviderRefusedContentError, ProviderRejectedRequestError
from application.ports.generation import Generation
from config.logging import log_event
from config.registry import RegistryFile
from domain.entities.model import Model
from domain.value_objects.finish_reason import FinishReason
from domain.value_objects.message import Message
from domain.value_objects.role import Role
from domain.value_objects.token_count import TokenCount
from domain.value_objects.usage import Usage
from infrastructure.providers.dialects import DIALECTS, Dialect

_MESSAGE_TYPES: dict[Role, type[HumanMessage]] = {Role.USER: HumanMessage}


class LangchainGenerationProvider:
    """One chat model per registry model, built at startup and shared by every pool thread.

    Repeats nothing and chooses no model: retries, failover and the budget are the use case's. What
    is a vendor's own — building its model, reading its stop reasons and errors — is its `Dialect`.

    Thread-safe: a call builds its prompt and options locally, and the chat models' HTTP clients are
    safe to share across threads.
    """

    def __init__(
        self, chat_models: Mapping[tuple[str, str], BaseChatModel], dialects: Mapping[str, Dialect]
    ) -> None:
        self._chat_models = dict(chat_models)
        self._dialects = dialects

    def generate(
        self,
        model: Model,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int,
        temperature: float | None,
        stop: list[str] | None,
        timeout_s: float,
        request_id: str,
    ) -> Generation:
        provider = model.provider.name.value
        dialect = self._dialects[provider]
        prompt: list[BaseMessage] = [SystemMessage(system)] if system else []
        # By role, so a role added to the domain fails here rather than going out as `user`. Turns
        # of one role in a row reach the vendor as one turn: langchain joins them, as the vendor
        # would.
        prompt += [_MESSAGE_TYPES[message.role](message.text) for message in messages]
        try:
            # Per call, over the chat model's own settings; an unset one is left out of the request.
            reply = self._chat_models[(provider, model.id.value)].invoke(
                prompt,
                stop=stop,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=dialect.timeout(timeout_s),
            )
        except Exception as error:  # a vendor failure and an adapter defect alike
            raise dialect.translate(error) from error

        if reply.usage_metadata is None or not dialect.reports_usage(reply.response_metadata):
            raise ProviderRejectedRequestError("the answer carried no usage", status=None)
        usage = Usage(
            input_tokens=TokenCount(reply.usage_metadata["input_tokens"]),
            output_tokens=TokenCount(reply.usage_metadata["output_tokens"]),
        )
        stop_reason = reply.response_metadata.get("stop_reason")
        if dialect.is_refusal(stop_reason):
            raise ProviderRefusedContentError(usage=usage)
        finish_reason = dialect.finish_reason(stop_reason)
        if finish_reason is None:
            # Outside the table: `tool_use`, `pause_turn`, or a value the vendor added since. The
            # answer is paid for — refusing it would lose the text and the accounting both, and the
            # next candidate would be paid again — so it is returned as a stop, and logged for the
            # table to catch up.
            log_event(
                "vendor_stop_reason_unmapped",
                level=logging.WARNING,
                request_id=request_id,
                provider=provider,
                model=model.id.value,
                vendor_stop_reason=str(stop_reason),
            )
            finish_reason = FinishReason.STOP
        # `str()`: langchain's text is a `str` subclass of its own, and it stops at this adapter.
        return Generation(text=str(reply.text), usage=usage, finish_reason=finish_reason)


def build_generation_provider(
    registry: RegistryFile, keys: Mapping[str, SecretStr], *, base_url: str | None = None
) -> LangchainGenerationProvider:
    """A chat model for every model of every enabled provider.

    :param base_url: The endpoint to talk to instead of the vendor's own: a local fake, in tests.
    """
    chat_models = {
        (provider, model_id): DIALECTS[provider].chat_model(
            model_id, keys[provider], base_url=base_url
        )
        for provider, entry in registry.providers.items()
        if entry.enabled
        for model_id in entry.models
    }
    return LangchainGenerationProvider(chat_models, DIALECTS)
