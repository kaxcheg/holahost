from __future__ import annotations

import uuid


class ChunkId(uuid.UUID):
    """Chunk identifier — a UUID (single representation; spec §7.1)."""

    @classmethod
    def new(cls) -> ChunkId:
        """Generate a fresh random identifier."""
        return cls(bytes=uuid.uuid4().bytes)

    @classmethod
    def from_str(cls, s: str) -> ChunkId:
        """Reconstruct an identifier from its canonical UUID string."""
        return cls(s)
