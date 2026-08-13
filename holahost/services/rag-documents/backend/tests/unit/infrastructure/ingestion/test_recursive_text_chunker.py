from __future__ import annotations

import pytest

from application.ports.ingestion import TextFragment
from domain.value_objects.page_number import PageNumber
from infrastructure.ingestion.recursive_text_chunker import RecursiveTextChunker


class TestRecursiveTextChunker:
    def test_short_fragment_becomes_one_chunk(self) -> None:
        chunker = RecursiveTextChunker(length_function=len, chunk_window=100, chunk_overlap=10)
        fragments = [TextFragment(text="short text", page=PageNumber(1))]

        chunks = chunker.split(fragments)

        assert len(chunks) == 1
        assert chunks[0].text == "short text"
        assert chunks[0].page.value == 1

    def test_long_fragment_splits_into_multiple_chunks(self) -> None:
        chunker = RecursiveTextChunker(length_function=len, chunk_window=20, chunk_overlap=5)
        long_text = " ".join(f"word{i}" for i in range(30))
        fragments = [TextFragment(text=long_text, page=PageNumber(1))]

        chunks = chunker.split(fragments)

        assert len(chunks) > 1
        assert all(len(c.text) <= 20 for c in chunks)

    def test_chunk_never_crosses_a_fragment_boundary(self) -> None:
        chunker = RecursiveTextChunker(length_function=len, chunk_window=10, chunk_overlap=0)
        fragments = [
            TextFragment(text="page one content here", page=PageNumber(1)),
            TextFragment(text="page two content here", page=PageNumber(2)),
        ]

        chunks = chunker.split(fragments)

        pages_seen = {c.page.value for c in chunks}
        assert pages_seen == {1, 2}
        assert all(c.page.value in (1, 2) for c in chunks)

    def test_preserves_pageless_fragments(self) -> None:
        chunker = RecursiveTextChunker(length_function=len, chunk_window=100, chunk_overlap=10)
        fragments = [TextFragment(text="pageless text", page=PageNumber(None))]

        chunks = chunker.split(fragments)

        assert all(c.page.value is None for c in chunks)

    def test_max_input_tokens_none_skips_the_check(self) -> None:
        # Default — must not raise even though chunk_window would "exceed" nothing
        # meaningful when length_function isn't token-based (e.g. tests' `len`).
        RecursiveTextChunker(length_function=len, chunk_window=10_000, chunk_overlap=0)

    def test_chunk_window_within_max_input_tokens_is_accepted(self) -> None:
        RecursiveTextChunker(
            length_function=len, chunk_window=100, chunk_overlap=10, max_input_tokens=128
        )

    def test_chunk_window_exceeding_max_input_tokens_raises(self) -> None:
        with pytest.raises(ValueError, match="exceeds the embedding model's max_input_tokens"):
            RecursiveTextChunker(
                length_function=len, chunk_window=200, chunk_overlap=10, max_input_tokens=128
            )
