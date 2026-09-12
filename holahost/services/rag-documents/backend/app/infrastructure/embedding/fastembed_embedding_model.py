from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import numpy.typing as npt
from fastembed import TextEmbedding

from application.ports.exceptions import EmbeddingFailedError
from domain.value_objects.embedding import Embedding


def _to_embedding(vector: npt.NDArray[Any]) -> Embedding:
    """`Any` dtype because fastembed's return type spans several, and all of them are
    normalized the same way here."""
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 0.0:
        arr = arr / norm
    return Embedding(tuple(float(x) for x in arr))


class FastembedEmbeddingModel:
    """Adapter for the `EmbeddingModel` port over one `fastembed.TextEmbedding`, loaded at
    construction and shared across the request threadpool. No lock: ONNX Runtime
    documents `InferenceSession.Run()` as thread-safe.

    `count_tokens` is not part of the port. It is an extra method the composition root
    uses to wire `RecursiveTextChunker`'s `length_function` to this model's own tokenizer,
    so the chunk window cannot drift from what the model actually tokenizes.
    """

    def __init__(self, model_name: str, cache_dir: str) -> None:
        # Mean pooling is this model's native strategy, so fastembed's version-change
        # notice is expected; silence that one warning, nothing else.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=".*now uses mean pooling.*", category=UserWarning
            )
            self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        self._dimension: int | None = None
        # What this tokenizer frames any input with: encoding the empty string yields
        # exactly its special tokens. Measured rather than assumed, so a model that frames
        # input differently keeps the two methods below correct.
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

        `add_special_tokens=False` is load-bearing: this is the chunker's
        `length_function`, measuring *fragments*, while framing tokens are added once per
        encoded sequence. Left on, every fragment reports tokens it does not contain, the
        splitter cuts early, and chunks come out a fraction of `CHUNK_WINDOW_TOKENS`.

        The tokenizer's truncation still applies inside `.encode()`, so the count saturates
        at its raw ceiling. Harmless for the splitter, which only asks "bigger than the
        window", and the window is guaranteed smaller than the ceiling at composition time
        (see `max_input_tokens`).
        """
        # fastembed's stubs omit `.model.tokenizer`; verified at runtime.
        return len(
            self._model.model.tokenizer.encode(  # type: ignore[attr-defined]
                text, add_special_tokens=False
            ).ids
        )

    def dimension(self) -> int:
        """How many components a vector from this model has, measured once.

        One `embed` of the empty string rather than a lookup in fastembed's model
        registry, whose shape has moved across the versions this project admits: what the
        schema must agree with is what `embed()` returns.

        Exposed so the composition root can refuse to start when the configured model does
        not produce the `EMBEDDING_DIM`-length vectors the `vector(384)` column and
        `Embedding`'s invariant are built around, instead of turning every ingest and
        search into a 500 for the life of the deployment.
        """
        if self._dimension is None:
            [vector] = list(self._model.embed([""]))
            self._dimension = int(np.asarray(vector).size)
        return self._dimension

    def max_input_tokens(self) -> int:
        """How many tokens of *content* this model accepts before it truncates the rest.

        The tokenizer's ceiling minus its framing tokens, and the subtraction is the point:
        truncation applies to the finished sequence, framing included, so reporting the raw
        ceiling would put a chunk measured at exactly the limit over it at embed time and
        drop the tail — silently, since `embed()` never raises for over-length input.

        Exposed so the composition root can fail fast when the configured chunk window
        exceeds what the model takes, instead of embedding truncated chunks for the life of
        the deployment.

        :raises RuntimeError: this model's tokenizer has no truncation configured —
            unexpected for any of fastembed's supported models (all have a fixed
            max sequence length baked into their architecture); surfaced loudly
            rather than returning a meaningless value.
        """
        truncation = self._model.model.tokenizer.truncation  # type: ignore[attr-defined]
        if truncation is None:
            raise RuntimeError("model's tokenizer has no truncation limit configured")
        return int(truncation["max_length"]) - self._special_token_overhead
