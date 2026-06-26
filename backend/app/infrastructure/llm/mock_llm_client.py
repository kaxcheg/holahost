from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr

from domain.entities.chunk import Chunk
from domain.entities.generated_reply import GeneratedReply
from domain.entities.guest_message import GuestMessage


class MockLLMClient:
    """Dev-only LLMClient stub: deterministic reply, no network (spec §12.1, C-01).

    Selected by the dev composition root under a feature flag (wiring is B-46). Echoes a fixed
    template referencing the retrieved-chunk count and the guest message, so the dev UI shows a
    plausible, deterministic response without an API key.

    Structurally conforms to the LLMClient port (no inheritance): see ``_conforms``.
    """

    def __init__(self, output_tokens: int = 42) -> None:
        """Init.

        Args:
            output_tokens: Fixed token count reported back (drives dev sample-budget math).
        """
        self._output_tokens = output_tokens

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
        """Return a deterministic canned reply (no upstream call; see port)."""
        text = f"[mock:{model_id}] {len(chunks)} chunks - re: {guest_message.text}"
        return GeneratedReply.create(text=text, output_tokens=self._output_tokens)


if TYPE_CHECKING:
    from application.ports.llm import LLMClient

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: MockLLMClient) -> LLMClient:
        return x
