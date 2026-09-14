"""Why generation stopped."""

from __future__ import annotations

from enum import StrEnum


class FinishReason(StrEnum):
    """Why generation stopped — the same value whichever provider answered.

    Each provider adapter maps its vendor's own reasons onto these. A stop sequence is not told
    apart from a natural end, because not every provider reports the difference. A content
    refusal is not a finish reason: it is a provider error.
    """

    STOP = "stop"
    MAX_TOKENS = "max_tokens"
