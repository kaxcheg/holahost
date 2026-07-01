from __future__ import annotations

import logging
import os
import time
import warnings
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
from fastembed import TextEmbedding

from config.logging import log_event
from domain.value_objects.embedding import Embedding


def _to_embedding(vector: npt.ArrayLike) -> Embedding:
    """Defensively L2-normalize a raw model vector and wrap it in the ``Embedding`` VO.

    fastembed's symmetric MiniLM output is already unit-norm; the explicit normalization guarantees
    the VO invariant (``|norm - 1| <= 1e-3``) regardless of model. Accepts any array-like (fastembed
    statically types ``embed`` with a broad float/int dtype union) and coerces to float32.

    :raises ValueError: if the vector is not 384-dim / not finite (propagated from the VO).
    """
    vec = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vec))
    if norm > 0.0:
        vec = (vec / norm).astype(np.float32)
    return Embedding(vector=vec)


class FastEmbedEmbeddingModel:
    """EmbeddingModel adapter over fastembed's local ONNX models (spec §8.2.2, C-04/C-05, D1).

    Wraps a single ``fastembed.TextEmbedding`` (weights downloaded/cached on first construction). The
    SAME instance is the single source of truth for tokenization: ``count_tokens`` (consumed by the
    TextChunker's ``length_function``) measures with the exact tokenizer the embedder applies, so the
    chunk-length guarantee cannot drift from the model (C-07).

    Structurally conforms to the EmbeddingModel port (no inheritance): see ``_conforms``.
    """

    def __init__(self, model_name: str) -> None:
        """Init.

        Args:
            model_name: fastembed registry id (must yield 384-dim vectors to match ``Embedding``).
        """
        # Baked-model cache observability (§2.1): an empty FASTEMBED_CACHE_PATH or a long load means the
        # weights were fetched from the network (cold-start cache miss), not reused from the baked image.
        cache_dir = os.environ.get("FASTEMBED_CACHE_PATH")
        cache_present = cache_dir is not None and os.path.isdir(cache_dir) and bool(os.listdir(cache_dir))
        start = time.monotonic()
        # Mean pooling is this model's native trained strategy (C-10); fastembed's version-change
        # notice (CLS -> mean) is expected -> silence only that one UserWarning, nothing else.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=".*now uses mean pooling.*", category=UserWarning
            )
            self._model = TextEmbedding(model_name=model_name)
        # Event name says cache HIT vs MISS; duration_ms (allowlisted, §10.5) is the load time. A miss is
        # logged at WARNING so the CloudWatch warning filter surfaces a cold start that re-downloaded the
        # model instead of reusing the baked image cache.
        log_event(
            "embedding_cache_hit" if cache_present else "embedding_cache_miss",
            level=logging.INFO if cache_present else logging.WARNING,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    def embed_one(self, text: str) -> Embedding:
        """Embed a single text (see port)."""
        [vector] = self._model.embed([text])
        return _to_embedding(vector)

    def embed_many(self, texts: list[str]) -> list[Embedding]:
        """Embed a batch, preserving input order (see port)."""
        return [_to_embedding(v) for v in self._model.embed(texts)]

    def count_tokens(self, text: str) -> int:
        """Count tokens with the embedder's OWN tokenizer (single source of truth, C-07).

        Consumed by the TextChunker's ``length_function`` so the chunk-window guarantee is measured
        against the exact tokenizer the embedder applies (including special tokens).

        Args:
            text: Text to measure.

        Returns:
            Token count.
        """
        # The concrete fastembed model exposes ``.tokenizer`` at runtime (verified, C-10); the
        # statically-typed base class (``TextEmbeddingBase``) omits it -> attr-defined ignore.
        return len(self._model.model.tokenizer.encode(text).ids)  # type: ignore[attr-defined]

    def max_input_tokens(self) -> int:
        """Max tokens the model embeds before silently truncating (the tokenizer's truncation ceiling).

        Exposes the model's real input limit (128 for the production MiniLM, D6) so the composition
        root (B-46) can fail-fast when ``max_chunk_tokens > max_input_tokens()`` — otherwise the
        embedder would silently truncate over-long chunks and degrade retrieval (§2.5 / C-07). The
        ``Settings`` validator cannot perform this check (it has no loaded model), so the guard lives
        at composition; this method is the seam for it.

        Returns:
            The tokenizer's truncation ``max_length``.

        :raises RuntimeError: if the tokenizer has no truncation configured (unexpected for the
            supported sentence-transformers models).
        """
        # ``.tokenizer`` exists on the concrete fastembed model at runtime (C-10); the static base
        # omits it -> attr-defined ignore. ``truncation`` is the ``{max_length, ...}`` config or None.
        truncation = self._model.model.tokenizer.truncation  # type: ignore[attr-defined]
        if truncation is None:
            raise RuntimeError("fastembed tokenizer has no truncation config")
        return int(truncation["max_length"])


if TYPE_CHECKING:
    from application.ports.embedding import EmbeddingModel

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: FastEmbedEmbeddingModel) -> EmbeddingModel:
        return x
