from __future__ import annotations

from typing import Protocol

from domain.entities.chunk import Chunk
from domain.value_objects.embedding import Embedding


class VectorSearch(Protocol):
    """Port: cosine top-K retrieval over chunk embeddings (spec §8.2.3)."""

    def top_k(self, query: Embedding, chunks: list[Chunk], k: int) -> list[Chunk]:
        """Return the ``k`` chunks most similar to ``query``.

        Args:
            query: Query embedding.
            chunks: Candidate chunks (each carries its embedding).
            k: Number of chunks to return.

        Returns:
            Up to ``k`` chunks ordered by descending cosine similarity.
        """
        ...
