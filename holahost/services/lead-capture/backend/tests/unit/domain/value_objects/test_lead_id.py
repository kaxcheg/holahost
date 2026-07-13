import uuid

import pytest

from domain.value_objects.lead_id import LeadId


class TestLeadId:
    def test_new_returns_lead_id_and_is_uuid(self) -> None:
        lid = LeadId.new()
        assert isinstance(lid, LeadId)
        assert isinstance(lid, uuid.UUID)

    def test_new_returns_unique_values(self) -> None:
        ids = {LeadId.new() for _ in range(1000)}
        assert len(ids) == 1000

    def test_from_str_round_trips_and_preserves_type(self) -> None:
        lid = LeadId.new()
        restored = LeadId.from_str(str(lid))
        assert restored == lid
        assert isinstance(restored, LeadId)

    def test_from_str_rejects_malformed(self) -> None:
        with pytest.raises(ValueError):
            LeadId.from_str("not-a-uuid")
