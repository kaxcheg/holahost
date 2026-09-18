"""What a generation will need, estimated before any provider is called.

Both checks built on these refuse without reaching outside, so neither can ask the provider: its
tokenizer is not published and counting through its API is a network call per request.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from application.limits import MAX_OUTPUT_TOKENS, MESSAGE_FRAMING_TOKENS
from domain.entities.model import Model
from domain.value_objects.message import Message


def estimate_input_tokens(system: str, messages: Sequence[Message]) -> int:
    """An upper bound on the input's tokens: its UTF-8 bytes plus framing per part.

    A bound rather than an average, because the context check must never let a request through
    that the provider then rejects for overflow. A byte-level tokenizer never produces more tokens
    than bytes; the price is overestimating dense scripts — Cyrillic by two to four times.

    :param system: The system instruction.
    :param messages: The conversation, in order.
    :return: The estimated token count.
    """
    parts = [system, *(message.text for message in messages)]
    return sum(len(part.encode("utf-8")) + MESSAGE_FRAMING_TOKENS for part in parts)


def output_ceiling(model: Model) -> int:
    """The largest answer `model` is allowed: the service's ceiling or the model's own, if lower."""
    return min(MAX_OUTPUT_TOKENS, model.max_output)


def effective_max_tokens(requested: int | None, model: Model) -> int:
    """The `max_tokens` a call to `model` runs with.

    :param requested: The caller's value, or `None` when it sent none.
    :param model: The model the call goes to — its own ceiling may be lower than the service's.
    :return: `requested` truncated to the ceiling, or the ceiling itself when nothing was requested.
    """
    ceiling = output_ceiling(model)
    return ceiling if requested is None else min(requested, ceiling)


def generation_seconds(max_tokens: int, model: Model) -> float:
    """How long a full-length answer takes at the model's conservative speed.

    Input processing is not added: without a measurement any figure for it would be invented, and
    an invented pessimistic one refuses requests that fit.
    """
    return max_tokens / model.tokens_per_second


def max_tokens_within(seconds: float, model: Model) -> int:
    """The largest `max_tokens` whose generation fits into `seconds`, never above the ceiling."""
    return max(0, min(math.floor(seconds * model.tokens_per_second), output_ceiling(model)))
