from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from domain.entities.chunk import Chunk
from domain.value_objects.embedding import Embedding


class NumpyVectorSearch:
    """VectorSearch adapter: cosine top-K over L2-normalized chunk embeddings (spec §8.2.3).

    Embeddings are unit-norm (the ``Embedding`` VO invariant), so cosine similarity == dot product.
    Returns up to ``k`` chunks by descending similarity; ties break by original index (stable sort).
    Empty candidates or ``k <= 0`` -> ``[]``.

    Structurally conforms to the VectorSearch port (no inheritance): see ``_conforms``.
    """

    def top_k(self, query: Embedding, chunks: list[Chunk], k: int) -> list[Chunk]:
        """Return the ``k`` chunks most similar to ``query`` (descending cosine; see port)."""
        if k <= 0 or not chunks:
            return []
        matrix = np.vstack([c.embedding.vector for c in chunks])  # (N, 384) float32
        scores = matrix @ query.vector  # (N,) cosine == dot, both unit-norm
        top = np.argsort(-scores, kind="stable")[:k]
        return [chunks[int(i)] for i in top]


if TYPE_CHECKING:
    from application.ports.vector import VectorSearch

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: NumpyVectorSearch) -> VectorSearch:
        return x
