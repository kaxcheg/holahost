from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GeneratedReply:
    """Transient entity holding the LLM-generated response (spec §7.7).

    Transient: not persisted; returned by LLMClient and consumed within one request.
    Equality by value (no id field).

    Args:
        text: The generated response text.
        output_tokens: Number of output tokens produced by the LLM.
    """

    text: str
    output_tokens: int

    @classmethod
    def create(cls, text: str, output_tokens: int) -> GeneratedReply:
        """Construct a GeneratedReply from LLM output.

        Args:
            text: Generated response text.
            output_tokens: Token count reported by the LLM.

        Returns:
            A new GeneratedReply instance.
        """
        return cls(text=text, output_tokens=output_tokens)
