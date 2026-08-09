"""Protocol for the embedding model used on both ingest and search."""

from __future__ import annotations

from typing import Protocol

from domain.value_objects.embedding import Embedding


class EmbeddingModel(Protocol):
    """Computes L2-normalized embedding vectors for chunk text and search queries.

    The same model instance and weights must be used for both ``embed_texts`` (ingest)
    and ``embed_query`` (search) — otherwise cosine similarity is meaningless (§3.6).

    Concurrency: implementations must be thread-safe. The model is loaded once per
    process (A-9) and called concurrently from the request threadpool's worker threads.
    """

    def embed_texts(self, texts: list[str]) -> list[Embedding]:
        """Embed a batch of chunk texts, in order.

        Args:
            texts: Chunk texts to embed.

        Returns:
            One embedding per input text, same order.

        Raises:
            EmbeddingFailedError: the model failed to produce an embedding.
        """
        ...

    def embed_query(self, text: str) -> Embedding:
        """Embed a single search query.

        Args:
            text: The search query text.

        Returns:
            The query's embedding.

        Raises:
            EmbeddingFailedError: the model failed to produce an embedding.
        """
        ...
