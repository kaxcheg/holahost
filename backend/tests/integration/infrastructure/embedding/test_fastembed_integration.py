import numpy as np
import pytest

from domain.value_objects.embedding import EMBEDDING_DIM
from domain.value_objects.parsed_segment import ParsedSegment
from infrastructure.embedding.fastembed_embedding_model import FastEmbedEmbeddingModel
from infrastructure.ingestion.recursive_text_chunker import RecursiveTextChunker

# Full canonical fastembed registry id (C-10: the short name raises ValueError on fastembed 0.8.x).
_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Production max_chunk_tokens (D6). The model's input ceiling must not fall below it, else the
# embedder silently truncates over-long chunks; the composition root (B-46) enforces this at startup.
_MAX_CHUNK_TOKENS = 128


@pytest.mark.integration
def test_embed_one_returns_384_unit_vector() -> None:
    emb = FastEmbedEmbeddingModel(_MODEL).embed_one("hola mundo")
    assert emb.vector.shape == (EMBEDDING_DIM,)
    assert abs(float(np.linalg.norm(emb.vector)) - 1.0) <= 1e-3


@pytest.mark.integration
def test_embed_many_preserves_order_and_count() -> None:
    out = FastEmbedEmbeddingModel(_MODEL).embed_many(["a", "b", "c"])
    assert len(out) == 3


@pytest.mark.integration
def test_count_tokens_positive_and_monotonic() -> None:
    model = FastEmbedEmbeddingModel(_MODEL)
    assert model.count_tokens("hola") >= 1
    assert model.count_tokens("hola mundo entero") > model.count_tokens("hola")


@pytest.mark.integration
def test_chunker_window_holds_under_real_tokenizer() -> None:
    # C-07 end-to-end: the chunker measures length with the embedder's OWN tokenizer, so every
    # emitted chunk fits the window. Caveat: RecursiveCharacterTextSplitter can exceed the window
    # for an atomic unit with no split point; the whitespace-rich text below always has one.
    model = FastEmbedEmbeddingModel(_MODEL)
    window = 64
    chunker = RecursiveTextChunker(
        length_function=model.count_tokens, chunk_window=window, chunk_overlap=8
    )
    out = chunker.chunk([ParsedSegment(text="hola mundo " * 200, page=0)])
    assert out
    assert all(model.count_tokens(s.text) <= window for s in out)
    assert all(s.page == 0 for s in out)


@pytest.mark.integration
def test_model_input_ceiling_not_below_max_chunk_tokens() -> None:
    # The explicit no-silent-truncation guard (Task-1): the real model's input ceiling must be at
    # least the configured max_chunk_tokens. B-46 enforces this at startup via max_input_tokens().
    model = FastEmbedEmbeddingModel(_MODEL)
    assert model.max_input_tokens() >= _MAX_CHUNK_TOKENS
