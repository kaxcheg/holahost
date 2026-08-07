"""Chunk identifier."""

from __future__ import annotations

import uuid


class ChunkId(uuid.UUID):
    """A chunk's identifier — self-generating, never externally assigned (spec §4.1)."""

    @classmethod
    def new(cls) -> ChunkId:
        """Generate a fresh random identifier."""
        return cls(bytes=uuid.uuid4().bytes)

    @classmethod
    def from_str(cls, s: str) -> ChunkId:
        """Reconstruct an identifier from its canonical UUID string.

        :raises ValueError: `s` is not a well-formed UUID string.
        """
        return cls(s)
