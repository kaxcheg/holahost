import uuid

import pytest

from domain.value_objects.chunk_id import ChunkId


class TestChunkId:
    def test_new_returns_chunk_id_and_is_uuid(self) -> None:
        cid = ChunkId.new()
        assert isinstance(cid, ChunkId)
        assert isinstance(cid, uuid.UUID)

    def test_new_returns_unique_values(self) -> None:
        ids = {ChunkId.new() for _ in range(1000)}
        assert len(ids) == 1000

    def test_from_str_round_trips_and_preserves_type(self) -> None:
        cid = ChunkId.new()
        restored = ChunkId.from_str(str(cid))
        assert restored == cid
        assert isinstance(restored, ChunkId)

    def test_from_str_rejects_malformed(self) -> None:
        with pytest.raises(ValueError):
            ChunkId.from_str("not-a-uuid")
