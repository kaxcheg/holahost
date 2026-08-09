"""Tests for SimilarityScore (the concrete type in ports/vector.py; the VectorSearch
Protocol itself has no runtime behavior to test)."""

from __future__ import annotations

import pytest

from application.ports.vector import SimilarityScore


class TestSimilarityScore:
    def test_accepts_a_value_in_range(self) -> None:
        assert SimilarityScore(0.42).value == 0.42

    def test_accepts_the_boundary_values(self) -> None:
        assert SimilarityScore(-1.0).value == -1.0
        assert SimilarityScore(1.0).value == 1.0

    def test_rejects_a_value_above_one(self) -> None:
        with pytest.raises(ValueError, match="range"):
            SimilarityScore(1.1)

    def test_rejects_a_value_below_negative_one(self) -> None:
        with pytest.raises(ValueError, match="range"):
            SimilarityScore(-1.1)
