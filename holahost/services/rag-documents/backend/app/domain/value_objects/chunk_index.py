"""A chunk's position within its document."""

from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class ChunkIndex:
    """A chunk's position within its document — >= 0.

    Cross-chunk invariants ("unique, no gaps within the document") are a
    whole-collection property this single-value VO cannot check — enforced
    wherever the full chunk collection is assembled (the chunker, or the use
    case), not here.

    :param value: The zero-based position.
    """

    value: int

    def __post_init__(self) -> None:
        # Chunker-computed, not client input — a negative value is an
        # internal defect, so `field` stays None.
        if self.value < 0:
            raise DomainValidationError("ChunkIndex must not be negative")
