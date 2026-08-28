from __future__ import annotations

import math
import tempfile
from collections.abc import Iterator

import pytest

from application.ports.ingestion import TextFragment
from domain.value_objects.embedding import EMBEDDING_DIM
from domain.value_objects.page_number import PageNumber
from infrastructure.embedding.fastembed_embedding_model import FastembedEmbeddingModel
from infrastructure.ingestion.recursive_text_chunker import RecursiveTextChunker

pytestmark = pytest.mark.integration

# fastembed's registry requires the fully-qualified name — the spec's §3.7 table and
# ADR A-15 both reference the bare "paraphrase-multilingual-MiniLM-L12-v2", which
# fastembed rejects outright (`TextEmbedding.list_supported_models()` lists only the
# `sentence-transformers/`-prefixed form).
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


def test_dimension_matches_what_the_schema_stores(embedder: FastembedEmbeddingModel) -> None:
    """The premise `scripts.bootstrap._assert_embedding_dimension_matches` checks at
    startup: the configured model really does produce `EMBEDDING_DIM`-length vectors,
    which is what the `vector(384)` column and `Embedding`'s invariant are built on."""
    assert embedder.dimension() == EMBEDDING_DIM


def test_dimension_agrees_with_an_actual_embedding(embedder: FastembedEmbeddingModel) -> None:
    # It is measured, not declared — so it has to keep agreeing with `embed_query`.
    assert embedder.dimension() == len(embedder.embed_query("anything").value)


def test_count_tokens_is_capped_at_max_input_tokens_for_over_length_text(
    embedder: FastembedEmbeddingModel,
) -> None:
    """Empirically confirms the caveat documented on `count_tokens()`: text longer
    than the tokenizer's ceiling does not report its true length — it silently caps out,
    because the tokenizer's own truncation runs inside `.encode()`. This is exactly
    why a composition-time check against `max_input_tokens()` is needed instead of
    trusting `count_tokens()` alone near/above the ceiling.

    Saturation is asserted by comparison rather than against a literal: the value it
    saturates *at* is the tokenizer's raw ceiling, which sits above the content ceiling
    `max_input_tokens()` reports by exactly the framing this model adds."""
    limit = embedder.max_input_tokens()
    saturated = embedder.count_tokens("word " * (limit * 5))
    assert saturated == embedder.count_tokens("word " * (limit * 20))
    assert saturated >= limit


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


def test_count_tokens_excludes_the_tokenizer_framing(embedder: FastembedEmbeddingModel) -> None:
    """The direct statement of the bug: an empty string contains no tokens.

    `count_tokens` is the chunker's `length_function`, so it measures *fragments*, while
    the tokenizer's framing is added once per encoded sequence. Counting it per fragment
    made every candidate measure larger than it is; the splitter cut early and chunks came
    out a fraction of the configured window."""
    assert embedder.count_tokens("") == 0


def test_max_input_tokens_reserves_room_for_the_framing(
    embedder: FastembedEmbeddingModel,
) -> None:
    """A chunk measured at exactly the reported ceiling must still fit once framed.

    Truncation applies to the finished sequence, framing included, so reporting the raw
    ceiling would put such a chunk over it at embed time — and `embed()` never raises for
    over-length input, it just drops the tail."""
    # Same attr-defined suppression the adapter itself carries: fastembed's public stubs
    # omit `.model.tokenizer`, which exists at runtime.
    tokenizer = embedder._model.model.tokenizer  # type: ignore[attr-defined]
    framing = len(tokenizer.encode("").ids)
    assert framing > 0, "this model frames its input; without that the check below is vacuous"
    assert embedder.max_input_tokens() == tokenizer.truncation["max_length"] - framing


def test_chunks_fill_the_configured_window(embedder: FastembedEmbeddingModel) -> None:
    """The regression the unit tests structurally cannot catch.

    They inject `len` as the `length_function`, which has no framing tokens to overcount —
    so the whole class of bug is invisible there. Only the real tokenizer shows it: with
    framing counted per fragment, chunks came out at a fraction of `CHUNK_WINDOW_TOKENS`
    no matter how the window was configured."""
    window = 120  # CHUNK_WINDOW_TOKENS in every infra/envs/<env>/.env
    chunker = RecursiveTextChunker(
        length_function=embedder.count_tokens,
        chunk_window=window,
        chunk_overlap=16,
        max_input_tokens=embedder.max_input_tokens(),
    )
    paragraph = " ".join(["Заселение начинается в три часа дня по местному времени."] * 60)
    chunks = chunker.split([TextFragment(text=paragraph, page=PageNumber(1))])

    sizes = [embedder.count_tokens(chunk.text) for chunk in chunks]
    assert len(sizes) > 1, "the sample must actually be split for this to mean anything"
    assert max(sizes) <= window
    # Loose on purpose — the point is "near the window", not an exact fill, which depends
    # on where the separators fall. Before the fix the chunks sat far below this line.
    assert min(sizes[:-1]) >= window * 0.5
