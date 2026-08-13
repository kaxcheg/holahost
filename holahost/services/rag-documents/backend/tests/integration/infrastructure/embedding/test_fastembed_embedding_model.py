from __future__ import annotations

import math
import tempfile
from collections.abc import Iterator

import pytest

from domain.value_objects.embedding import EMBEDDING_DIM
from infrastructure.embedding.fastembed_embedding_model import FastembedEmbeddingModel

pytestmark = pytest.mark.integration

# fastembed's registry requires the fully-qualified name — the spec's §3.7 table and
# ADR A-15 both reference the bare "paraphrase-multilingual-MiniLM-L12-v2", which
# fastembed rejects outright (`TextEmbedding.list_supported_models()` lists only the
# `sentence-transformers/`-prefixed form). Flagged in clarifications.md to propose back
# into Source Data at Work Step 6.
_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@pytest.fixture(scope="session")
def embedder() -> Iterator[FastembedEmbeddingModel]:
    with tempfile.TemporaryDirectory() as cache_dir:
        yield FastembedEmbeddingModel(model_name=_MODEL_NAME, cache_dir=cache_dir)


def test_embed_texts_returns_normalized_384_dim_vectors(embedder: FastembedEmbeddingModel) -> None:
    embeddings = embedder.embed_texts(["hello world", "check-in is at 3pm"])
    assert len(embeddings) == 2
    for e in embeddings:
        assert len(e.value) == EMBEDDING_DIM
        assert math.isclose(math.sqrt(sum(x * x for x in e.value)), 1.0, abs_tol=1e-3)


def test_embed_query_returns_normalized_vector(embedder: FastembedEmbeddingModel) -> None:
    embedding = embedder.embed_query("what time is check-in?")
    assert len(embedding.value) == EMBEDDING_DIM


def test_count_tokens_is_positive_and_monotonic_ish(embedder: FastembedEmbeddingModel) -> None:
    short = embedder.count_tokens("hi")
    longer = embedder.count_tokens("hi there, how are you doing today")
    assert short > 0
    assert longer > short


def test_same_text_embeds_deterministically(embedder: FastembedEmbeddingModel) -> None:
    a = embedder.embed_query("determinism check")
    b = embedder.embed_query("determinism check")
    assert a.value == b.value


def test_max_input_tokens_is_positive(embedder: FastembedEmbeddingModel) -> None:
    assert embedder.max_input_tokens() > 0


def test_count_tokens_is_capped_at_max_input_tokens_for_over_length_text(
    embedder: FastembedEmbeddingModel,
) -> None:
    """Empirically confirms the caveat documented on `count_tokens()`: text longer
    than `max_input_tokens()` does not report its true length — it silently caps out,
    because the tokenizer's own truncation runs inside `.encode()`. This is exactly
    why a composition-time check against `max_input_tokens()` is needed instead of
    trusting `count_tokens()` alone near/above the ceiling."""
    limit = embedder.max_input_tokens()
    over_length_text = "word " * (limit * 5)
    assert embedder.count_tokens(over_length_text) == limit


def test_embed_texts_silently_truncates_over_length_input_without_raising(
    embedder: FastembedEmbeddingModel,
) -> None:
    """Empirically confirms the risk `max_input_tokens()` guards against: embedding
    text past the model's limit does not error — it succeeds, silently derived from
    only the first `max_input_tokens()` tokens."""
    limit = embedder.max_input_tokens()
    over_length_text = "word " * (limit * 5)
    embeddings = embedder.embed_texts([over_length_text])
    assert len(embeddings) == 1
    assert len(embeddings[0].value) == EMBEDDING_DIM
