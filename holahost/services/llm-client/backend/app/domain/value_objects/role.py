"""The author of a message."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Who wrote a message.

    There is no `system` role: the system instruction is a request field of its own, so it cannot
    end up after untrusted content or be lost when messages are concatenated.

    There is no `assistant` role either, until a caller holds a multi-turn conversation. Allowed
    without the turn-order rules that come with one, it would let a request end on an `assistant`
    turn — a prefill some models accept and others reject — so re-pointing an alias would turn a
    working request into a provider error.
    """

    USER = "user"
