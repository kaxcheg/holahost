from __future__ import annotations

from typing import Protocol

from domain.value_objects.magic_link import MagicLink


class MagicLinkGenerator(Protocol):
    """Port: generate a fresh magic-link token (spec §8.2.7)."""

    def generate(self) -> MagicLink:
        """Generate a new unguessable magic link (charset/length invariants in the impl)."""
        ...
