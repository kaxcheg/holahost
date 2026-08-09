"""Tests for TextFragment (the concrete type in ports/ingestion.py; the FileParser/
TextChunker Protocols themselves have no runtime behavior to test)."""

from __future__ import annotations

import pytest

from application.ports.ingestion import TextFragment
from domain.value_objects.page_number import PageNumber


class TestTextFragment:
    def test_accepts_nonempty_text_with_a_page(self) -> None:
        fragment = TextFragment(text="hello world", page=PageNumber(1))
        assert fragment.text == "hello world"
        assert fragment.page.value == 1

    def test_accepts_nonempty_text_without_a_page(self) -> None:
        fragment = TextFragment(text="hello world", page=PageNumber(None))
        assert fragment.page.value is None

    def test_rejects_empty_text(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            TextFragment(text="   ", page=PageNumber(None))
