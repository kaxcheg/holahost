"""A chunk's or query's embedding vector."""

from __future__ import annotations

import math
from dataclasses import dataclass

EMBEDDING_DIM = 384  # spec §3.7 — paraphrase-multilingual-MiniLM-L12-v2
_NORM_TOLERANCE = 1e-6


@dataclass(frozen=True, slots=True)
class Embedding:
    """An L2-normalized embedding vector (spec §4.1).

    Normalization is an invariant, not a caller operation: the constructor
    rejects anything not already normalized, so cosine similarity in search
    reduces to a dot product and "forgot to normalize" is structurally
    impossible. Declared as `tuple[float, ...]` (not `numpy.ndarray`), which
    is natively hashable/comparable — no `eq=False` override needed, unlike
    an ndarray-backed version would require.

    :param value: The vector, length `EMBEDDING_DIM`.
    """

    value: tuple[float, ...]

    def __post_init__(self) -> None:
        # Embedder-computed, not client input — any violation here is an
        # internal defect, so plain ValueError throughout.
        if len(self.value) != EMBEDDING_DIM:
            raise ValueError(f"Embedding dimension must be {EMBEDDING_DIM}")
        if not all(math.isfinite(x) for x in self.value):
            raise ValueError("Embedding values must all be finite")
        norm = math.sqrt(sum(x * x for x in self.value))
        if abs(norm - 1.0) > _NORM_TOLERANCE:
            raise ValueError(f"Embedding must be L2-normalized (got norm={norm})")
