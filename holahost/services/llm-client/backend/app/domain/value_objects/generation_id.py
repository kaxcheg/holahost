"""Generation identifier."""

from __future__ import annotations

import uuid


class GenerationId(uuid.UUID):
    """Identifies one generation and the usage record it produces.

    Self-generating, never taken from the request. `X-Request-ID` is chosen by the caller and two
    paid generations may share it; this identifier is unique per generation, which is what lets
    the usage log's idempotent insert drop only a genuine re-insert of the same record.
    """

    @classmethod
    def new(cls) -> GenerationId:
        """Generate a fresh random identifier."""
        return cls(bytes=uuid.uuid4().bytes)
