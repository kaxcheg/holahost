"""Tests for search-related DTOs."""

from __future__ import annotations

import dataclasses

import pytest

from application.dto.search import SearchCmd, SearchHitView, SearchResult


class TestSearchCmd:
    def test_frozen(self) -> None:
        cmd = SearchCmd(document_id="id", owner="u", query="q")
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.query = "other"  # type: ignore[misc]


class TestSearchResult:
    def test_empty_hits_is_valid(self) -> None:
        result = SearchResult(hits=[])
        assert result.hits == []

    def test_holds_hit_views(self) -> None:
        hit = SearchHitView(chunk_id="c1", text="text", page=2, score=0.71)
        result = SearchResult(hits=[hit])
        assert result.hits[0].page == 2
