"""A search hit's cosine similarity to the query."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SimilarityScore:
    """Cosine similarity between two L2-normalized vectors — in [-1, 1] (spec §4.1).

    Belongs to the query↔chunk pair, not the chunk itself (spec §4.4) — not a
    `Chunk` field.

    :param value: The cosine similarity.
    """

    value: float

    def __post_init__(self) -> None:
        # Search-time computed, not client input — out-of-range is an
        # internal defect, so plain ValueError.
        if not (-1.0 <= self.value <= 1.0):
            raise ValueError("SimilarityScore must be in range [-1, 1]")
