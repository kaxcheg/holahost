import uuid

import pytest

from domain.value_objects.guidebook_id import GuidebookId


class TestGuidebookId:
    def test_new_returns_guidebook_id_and_is_uuid(self) -> None:
        gid = GuidebookId.new()
        assert isinstance(gid, GuidebookId)
        assert isinstance(gid, uuid.UUID)

    def test_new_returns_unique_values(self) -> None:
        ids = {GuidebookId.new() for _ in range(1000)}
        assert len(ids) == 1000

    def test_from_str_round_trips_and_preserves_type(self) -> None:
        gid = GuidebookId.new()
        restored = GuidebookId.from_str(str(gid))
        assert restored == gid
        assert isinstance(restored, GuidebookId)

    def test_from_str_rejects_malformed(self) -> None:
        with pytest.raises(ValueError):
            GuidebookId.from_str("not-a-uuid")
