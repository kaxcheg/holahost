from __future__ import annotations

from datetime import UTC, datetime, timedelta

from application.use_cases.cleanup_expired import CleanupExpiredUseCase
from domain.entities.lead import Lead
from domain.value_objects.lead_id import LeadId
from tests._support.builders import make_guidebook, make_lead
from tests._support.fakes import FakeGuidebooksRepo, FakeLeadsRepo, FakeUnitOfWork
from tests._support.settings import make_settings

_OLD = datetime.now(tz=UTC) - timedelta(days=40)


class _TouchOnRefetchLeadsRepo(FakeLeadsRepo):
    """Simulates a concurrent ``touch`` between ``list_expired`` and the locked re-fetch (§9.6)."""

    def get_by_id_for_update(self, id: LeadId) -> Lead | None:
        lead = super().get_by_id_for_update(id)
        if lead is not None:
            lead.touch()  # bump last_seen_at to now → re-check must skip this lead
        return lead


def _uc(leads: FakeLeadsRepo, gbs: FakeGuidebooksRepo) -> CleanupExpiredUseCase:
    return CleanupExpiredUseCase(
        leads_repo=leads,
        guidebooks_repo=gbs,
        uow=FakeUnitOfWork(),
        settings=make_settings(magic_link_ttl_days=30, cleanup_batch_size=100),
    )


class TestCleanupExpired:
    def test_expires_lead_and_deletes_guidebook(self) -> None:
        gb = make_guidebook()
        lead = make_lead(guidebook_id=gb.id, last_seen_at=_OLD)
        gbs = FakeGuidebooksRepo([gb])
        leads = FakeLeadsRepo([lead])
        result = _uc(leads, gbs).execute()
        assert result.expired_magic_links == 1
        assert result.deleted_guidebooks == 1
        assert gbs.get(gb.id) is None
        fresh = leads.get_by_id(lead.id)
        assert fresh is not None
        assert fresh.magic_link is None
        assert fresh.guidebook_id is None

    def test_capture_only_lead_expires_without_guidebook(self) -> None:
        lead = make_lead(guidebook_id=None, last_seen_at=_OLD)
        leads = FakeLeadsRepo([lead])
        result = _uc(leads, FakeGuidebooksRepo()).execute()
        assert result.expired_magic_links == 1
        assert result.deleted_guidebooks == 0

    def test_recently_seen_lead_is_skipped(self) -> None:
        lead = make_lead(last_seen_at=datetime.now(tz=UTC))
        leads = FakeLeadsRepo([lead])
        result = _uc(leads, FakeGuidebooksRepo()).execute()
        assert result.expired_magic_links == 0
        fresh = leads.get_by_id(lead.id)
        assert fresh is not None
        assert fresh.magic_link is not None

    def test_empty_set_returns_zeroes(self) -> None:
        result = _uc(FakeLeadsRepo(), FakeGuidebooksRepo()).execute()
        assert result.expired_magic_links == 0
        assert result.deleted_guidebooks == 0

    def test_concurrent_touch_between_batch_and_refetch_skips(self) -> None:
        # list_expired yields the lead (last_seen old), but the re-fetch sees a fresh last_seen_at
        # (a concurrent touch). The §9.6 re-check must skip it without expiring.
        gb = make_guidebook()
        lead = make_lead(guidebook_id=gb.id, last_seen_at=_OLD)
        leads = _TouchOnRefetchLeadsRepo([lead])
        gbs = FakeGuidebooksRepo([gb])
        result = _uc(leads, gbs).execute()
        assert result.expired_magic_links == 0
        assert result.deleted_guidebooks == 0
        assert gbs.get(gb.id) is not None
        fresh = leads.get_by_id(lead.id)
        assert fresh is not None
        assert fresh.magic_link is not None
