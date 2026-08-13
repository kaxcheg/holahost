from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import numpy.typing as npt
from fastembed import TextEmbedding

from application.ports.exceptions import EmbeddingFailedError
from domain.value_objects.embedding import Embedding


def _to_embedding(vector: npt.NDArray[Any]) -> Embedding:
    """`vector` is whichever dtype `TextEmbedding.embed`/`query_embed` yielded
    (float64/float32/float16/int8/int64/int32, per fastembed's own return type) —
    `Any` here, not a narrower dtype, because this function normalizes all of them
    the same way regardless of which one arrived."""
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 0.0:
        arr = arr / norm
    return Embedding(tuple(float(x) for x in arr))


class FastembedEmbeddingModel:
    """Adapter for the `EmbeddingModel` port over a single `fastembed.TextEmbedding`
    instance, loaded once at construction and shared across the request threadpool
    (A-9). Thread-safety is ONNX Runtime's own guarantee (`InferenceSession.Run()` is
    documented thread-safe; the Python binding releases the GIL for it) — no lock here.

    `count_tokens` is deliberately NOT part of the `EmbeddingModel` Protocol (the
    application-layer port doesn't declare it); it's an extra method the composition
    root (R-24) uses to wire `RecursiveTextChunker`'s `length_function` to this exact
    model's own tokenizer, so the chunk-window guarantee can never drift from what the
    model actually tokenizes.
    """

    def __init__(self, model_name: str, cache_dir: str) -> None:
        # Mean pooling is this model's native trained strategy — fastembed's
        # version-change notice (CLS -> mean) is expected, not actionable; silence
        # only that one UserWarning, nothing else.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=".*now uses mean pooling.*", category=UserWarning
            )
            self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed_texts(self, texts: list[str]) -> list[Embedding]:
        try:
            return [_to_embedding(v) for v in self._model.embed(texts)]
        except Exception as e:  # fastembed/onnxruntime raise plain Exception/RuntimeError
            raise EmbeddingFailedError from e

    def embed_query(self, text: str) -> Embedding:
        try:
            [vector] = list(self._model.query_embed(text))
            return _to_embedding(vector)
        except Exception as e:
            raise EmbeddingFailedError from e

    def count_tokens(self, text: str) -> int:
        """Count tokens with this exact model's own tokenizer (composition-time use).

        Caveat verified at runtime: the tokenizer's own truncation kicks in *inside*
        `.encode()`, so this silently caps out at `max_input_tokens()` for `text`
        longer than that — it does not report the true count past the ceiling. Safe
        as a chunker `length_function` only as long as the configured chunk window
        stays below `max_input_tokens()` (checked once at composition time, not here
        per-call — see that method).
        """
        # fastembed's public type stubs omit `.model.tokenizer`; verified at runtime
        # (~/repos/lead-capture precedent) — attr-defined ignore, not a guess.
        return len(self._model.model.tokenizer.encode(text).ids)  # type: ignore[attr-defined]

    def max_input_tokens(self) -> int:
        """Max tokens this model's tokenizer accepts before silently truncating the
        rest — verified at runtime: a deliberately over-length input truncates to
        exactly this many tokens with no error, `embed()`/`query_embed()` never raise
        for over-length input, they just drop the tail. Exposes the model's real
        limit so the composition root can fail fast at startup if
        `RecursiveTextChunker`'s configured window ever exceeds what this model
        actually supports, instead of silently embedding truncated chunks later.

        :raises RuntimeError: this model's tokenizer has no truncation configured —
            unexpected for any of fastembed's supported models (all have a fixed
            max sequence length baked into their architecture); surfaced loudly
            rather than returning a meaningless value.
        """
        truncation = self._model.model.tokenizer.truncation  # type: ignore[attr-defined]
        if truncation is None:
            raise RuntimeError("model's tokenizer has no truncation limit configured")
        return int(truncation["max_length"])
