from __future__ import annotations

from typing import Protocol

from pydantic import SecretStr

from domain.entities.chunk import Chunk
from domain.entities.generated_reply import GeneratedReply
from domain.entities.guest_message import GuestMessage


class LLMClient(Protocol):
    """Port: generate a reply from retrieved context (spec §8.2.4)."""

    def generate(
        self,
        chunks: list[Chunk],
        guest_message: GuestMessage,
        model_id: str,
        system_prompt: str,
        max_output_tokens: int,
        api_key: SecretStr,
    ) -> GeneratedReply:
        """Generate a reply for ``guest_message`` grounded in ``chunks``.

        Args:
            chunks: Top-K retrieved chunks; the impl builds the prompt from ``chunk.text``.
            guest_message: The guest's message entity.
            model_id: Model identifier (from Settings).
            system_prompt: System prompt (from Settings).
            max_output_tokens: Output cap (from Settings; ``> 0`` enforced in Settings).
            api_key: Server key (sample) or BYOK (real); SecretStr.

        Returns:
            The generated reply entity.

        Raises:
            InvalidApiKeyError: upstream 401 on a BYOK key (§9.5 / §9.8).
            UpstreamLLMError: upstream 429/5xx, or 401 on the server key (§9.1 / §9.8).
        """
        ...
