import pytest

from domain.value_objects.chunk_index import ChunkIndex


class TestChunkIndex:
    def test_accepts_zero(self) -> None:
        assert ChunkIndex(0).value == 0

    def test_accepts_a_positive_value(self) -> None:
        assert ChunkIndex(5).value == 5

    def test_rejects_a_negative_value(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            ChunkIndex(-1)
