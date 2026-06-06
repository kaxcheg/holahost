from __future__ import annotations

import uuid


class LeadId(uuid.UUID):
    """Lead identifier — a UUID (single representation; spec §7.1)."""

    @classmethod
    def new(cls) -> LeadId:
        """Generate a fresh random identifier."""
        return cls(bytes=uuid.uuid4().bytes)

    @classmethod
    def from_str(cls, s: str) -> LeadId:
        """Reconstruct an identifier from its canonical UUID string."""
        return cls(s)
