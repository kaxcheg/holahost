"""Token usage."""

from __future__ import annotations

from dataclasses import dataclass

from domain.value_objects.token_count import TokenCount


@dataclass(frozen=True, slots=True)
class Usage:
    """Input and output tokens, counted separately.

    Two counters rather than one sum: input and output are priced differently, so a single number
    would misstate spend.

    :param input_tokens: Tokens of `system` and `messages`.
    :param output_tokens: Tokens of the generated answer.
    """

    input_tokens: TokenCount
    output_tokens: TokenCount
