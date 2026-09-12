"""Document identifier."""

from __future__ import annotations

import uuid


class DocumentId(uuid.UUID):
    """A document's identifier — self-generating, never externally assigned."""

    @classmethod
    def new(cls) -> DocumentId:
        """Generate a fresh random identifier."""
        return cls(bytes=uuid.uuid4().bytes)

    @classmethod
    def from_str(cls, s: str) -> DocumentId:
        """Reconstruct an identifier from its canonical UUID string.

        :raises ValueError: `s` is not a well-formed UUID string — `uuid.UUID`'s
            own error, not wrapped: this is Python's own well-known message,
            and by the time this is called the interface layer has typically
            already shape-validated the path/body param as UUID-like.
        """
        return cls(s)
