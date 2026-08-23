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
        # Measured once, not assumed: what this tokenizer adds around any input. Encoding
        # the empty string yields exactly the special tokens and nothing else (verified:
        # 2 for this model — `<s>`/`</s>`). Reading it off the tokenizer keeps the two
        # methods below correct for a model that frames its input differently.
        self._special_token_overhead = len(
            self._model.model.tokenizer.encode("").ids  # type: ignore[attr-defined]
        )

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
        """Count the tokens `text` itself contributes, with this model's own tokenizer.

        `add_special_tokens=False` is load-bearing, not a detail. This is the chunker's
        `length_function`, so it is asked to measure *fragments* — and the tokenizer's
        framing tokens are added once per encoded sequence, not once per fragment. Left
        on, every fragment measured anywhere in the recursive split reports two tokens it
        does not contain (verified: `count_tokens("") == 2`), so the splitter believes
        each candidate is larger than it is and cuts early. The overcount compounds across
        splits and separators, and chunks come out a fraction of `CHUNK_WINDOW_TOKENS`.

        Caveat verified at runtime: the tokenizer's own truncation still applies inside
        `.encode()`, so the count saturates at the tokenizer's raw ceiling for text longer
        than that — it does not report the true length past it. Harmless for the splitter,
        which only needs "is this bigger than the window", and the window is guaranteed
        smaller than the ceiling at composition time (see `max_input_tokens`).
        """
        # fastembed's public type stubs omit `.model.tokenizer`; verified at runtime
        # (~/repos/lead-capture precedent) — attr-defined ignore, not a guess.
        return len(
            self._model.model.tokenizer.encode(  # type: ignore[attr-defined]
                text, add_special_tokens=False
            ).ids
        )

    def max_input_tokens(self) -> int:
        """How many tokens of *content* this model accepts before it truncates the rest.

        The tokenizer's own ceiling minus its framing tokens, and the subtraction is the
        point: truncation applies to the finished sequence, framing included (verified —
        over-length input comes back at exactly the ceiling either way, so with framing on
        it holds two fewer tokens of the caller's text). Reporting the raw ceiling would
        put a chunk measured by `count_tokens` at exactly the limit two tokens over it at
        embed time, and the tail would be dropped — silently, since `embed()` never raises
        for over-length input.

        Exposed so the composition root can fail fast at startup when the configured chunk
        window exceeds what the model really takes, instead of embedding truncated chunks
        for the rest of the deployment.

        :raises RuntimeError: this model's tokenizer has no truncation configured —
            unexpected for any of fastembed's supported models (all have a fixed
            max sequence length baked into their architecture); surfaced loudly
            rather than returning a meaningless value.
        """
        truncation = self._model.model.tokenizer.truncation  # type: ignore[attr-defined]
        if truncation is None:
            raise RuntimeError("model's tokenizer has no truncation limit configured")
        return int(truncation["max_length"]) - self._special_token_overhead
