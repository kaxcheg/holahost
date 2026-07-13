from __future__ import annotations

from typing import Protocol

from domain.value_objects.embedding import Embedding


class EmbeddingModel(Protocol):
    """Port: produce L2-normalized embeddings from text (spec §8.2.2).

    The port consumes the primitive ``str`` and produces the ``Embedding`` VO.
    """

    def embed_one(self, text: str) -> Embedding:
        """Embed a single text.

        Args:
            text: Text to embed.

        Returns:
            The embedding VO.
        """
        ...

    def embed_many(self, texts: list[str]) -> list[Embedding]:
        """Embed a batch of texts.

        Args:
            texts: Texts to embed.

        Returns:
            Embeddings in input order.
        """
        ...
