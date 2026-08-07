import uuid

import pytest

from domain.value_objects.chunk_id import ChunkId


class TestChunkId:
    def test_new_generates_a_valid_uuid(self) -> None:
        chunk_id = ChunkId.new()
        assert isinstance(chunk_id, uuid.UUID)
        assert isinstance(chunk_id, ChunkId)

    def test_new_generates_distinct_ids(self) -> None:
        assert ChunkId.new() != ChunkId.new()

    def test_from_str_reconstructs_the_same_id(self) -> None:
        original = ChunkId.new()
        assert ChunkId.from_str(str(original)) == original

    def test_from_str_rejects_a_malformed_string(self) -> None:
        with pytest.raises(ValueError, match="badly formed"):
            ChunkId.from_str("not-a-uuid")
