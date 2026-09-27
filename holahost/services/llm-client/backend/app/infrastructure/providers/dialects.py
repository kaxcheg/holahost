"""What differs between vendors behind the langchain chat-model interface, and which vendors have an
adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from application.ports.exceptions import ProviderRejectedRequestError, TransientProviderError
from domain.value_objects.finish_reason import FinishReason
from infrastructure.providers.anthropic_dialect import AnthropicDialect


class Dialect(Protocol):
    """One vendor's side of the generation adapter: its chat model, its stop reasons, its errors."""

    def chat_model(
        self, model_id: str, api_key: SecretStr, *, base_url: str | None
    ) -> BaseChatModel:
        """A chat model with the SDK's own retries off; `base_url` replaces the vendor's
        endpoint."""
        ...

    def timeout(self, seconds: float) -> object:
        """An attempt's timeout in the form the vendor's SDK takes: `seconds` for the answer, and
        setting up the call bounded apart."""
        ...

    def finish_reason(self, stop_reason: object) -> FinishReason | None:
        """The stop reason in the port's terms; `None` outside the vendor's table."""
        ...

    def is_refusal(self, stop_reason: object) -> bool:
        """Whether the model declined the content."""
        ...

    def reports_usage(self, response_metadata: Mapping[str, object]) -> bool:
        """Whether the vendor's answer carried its figures. Asked of the vendor's own metadata:
        langchain fills a missing usage with zeros, which would pass for confirmed spend."""
        ...

    def translate(self, error: Exception) -> TransientProviderError | ProviderRejectedRequestError:
        """A failed call in the port's terms."""
        ...


DIALECTS: Mapping[str, Dialect] = {"anthropic": AnthropicDialect()}
"""Every vendor the service can talk to, by the provider name the registry uses."""
