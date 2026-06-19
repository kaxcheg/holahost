from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from application.dto.leads import ResolveMagicLinkCmd
from application.exceptions import InvalidMagicLinkError, RateLimitExceededError
from application.ports.rate import RateLimitScope
from application.use_cases.resolve_magic_link import ResolveMagicLinkUseCase
from config.config import Settings
from tests._support.builders import make_guidebook, make_lead, make_magic_link
from tests._support.fakes import (
    FakeGuidebooksRepo,
    FakeLeadsRepo,
    FakeRateLimiter,
    FakeUnitOfWork,
)
from tests._support.settings import make_settings


def _uc(
    leads: FakeLeadsRepo,
    gbs: FakeGuidebooksRepo,
    rate: FakeRateLimiter | None = None,
    settings: Settings | None = None,
) -> ResolveMagicLinkUseCase:
    return ResolveMagicLinkUseCase(
        rate=rate or FakeRateLimiter(),
        leads_repo=leads,
        guidebooks_repo=gbs,
        uow=FakeUnitOfWork(),
        settings=settings or make_settings(),
    )


class TestResolveMagicLink:
    def test_resolves_with_guidebook(self) -> None:
        gb = make_guidebook(name="Riverside Loft")
        lead = make_lead(magic_link=make_magic_link("live-token"), guidebook_id=gb.id)
        uc = _uc(FakeLeadsRepo([lead]), FakeGuidebooksRepo([gb]))
        res = uc.execute(ResolveMagicLinkCmd(magic_link=SecretStr("live-token"), ip_hash="h"))
        assert res.email == lead.email.value
        assert res.flow == lead.flow.value
        assert res.guidebook_id == str(gb.id)
        assert res.guidebook_name == "Riverside Loft"
        assert res.guidebook_created_at == gb.created_at.isoformat()

    def test_resolves_without_guidebook(self) -> None:
        lead = make_lead(magic_link=make_magic_link("t2"), guidebook_id=None)
        uc = _uc(FakeLeadsRepo([lead]), FakeGuidebooksRepo())
        res = uc.execute(ResolveMagicLinkCmd(magic_link=SecretStr("t2"), ip_hash="h"))
        assert res.guidebook_id is None
        assert res.guidebook_name is None
        assert res.guidebook_created_at is None

    def test_unknown_token_raises_invalid(self) -> None:
        uc = _uc(FakeLeadsRepo(), FakeGuidebooksRepo())
        with pytest.raises(InvalidMagicLinkError):
            uc.execute(ResolveMagicLinkCmd(magic_link=SecretStr("nope"), ip_hash="h"))

    def test_empty_token_raises_invalid(self) -> None:
        # Empty token → 401 InvalidMagicLinkError (via magic_link_validation), not 422 (§9.8).
        uc = _uc(FakeLeadsRepo(), FakeGuidebooksRepo())
        with pytest.raises(InvalidMagicLinkError):
            uc.execute(ResolveMagicLinkCmd(magic_link=SecretStr(""), ip_hash="h"))

    def test_inactive_lead_returns_null_guidebook_without_deleting(self) -> None:
        # Signal is lead.last_seen_at (§10.1): an inactive lead soft-nulls the guidebook view,
        # without deleting the row (cleanup hard-deletes later).
        gb = make_guidebook()
        lead = make_lead(
            magic_link=make_magic_link("t3"),
            guidebook_id=gb.id,
            last_seen_at=datetime.now(tz=UTC) - timedelta(days=40),
        )
        gbs = FakeGuidebooksRepo([gb])
        uc = _uc(FakeLeadsRepo([lead]), gbs, settings=make_settings(magic_link_ttl_days=30))
        res = uc.execute(ResolveMagicLinkCmd(magic_link=SecretStr("t3"), ip_hash="h"))
        assert res.guidebook_id is None
        assert gbs.get(gb.id) is not None  # soft expire: not deleted

    def test_rate_ip_checked_before_resolve(self) -> None:
        rate = FakeRateLimiter(raise_on={RateLimitScope.IP})
        uc = _uc(FakeLeadsRepo(), FakeGuidebooksRepo(), rate=rate)
        with pytest.raises(RateLimitExceededError):
            uc.execute(ResolveMagicLinkCmd(magic_link=SecretStr("x"), ip_hash="h"))
        assert rate.calls == [(RateLimitScope.IP, "h")]

    def test_magic_link_rate_subject_is_lead_id(self) -> None:
        lead = make_lead(magic_link=make_magic_link("t4"))
        rate = FakeRateLimiter()
        uc = _uc(FakeLeadsRepo([lead]), FakeGuidebooksRepo(), rate=rate)
        uc.execute(ResolveMagicLinkCmd(magic_link=SecretStr("t4"), ip_hash="h"))
        assert (RateLimitScope.MAGIC_LINK, str(lead.id)) in rate.calls

    def test_touch_bumps_last_seen(self) -> None:
        old = datetime.now(tz=UTC) - timedelta(days=1)
        lead = make_lead(magic_link=make_magic_link("t5"), last_seen_at=old)
        leads = FakeLeadsRepo([lead])
        _uc(leads, FakeGuidebooksRepo()).execute(
            ResolveMagicLinkCmd(magic_link=SecretStr("t5"), ip_hash="h")
        )
        fresh = leads.get_by_id(lead.id)
        assert fresh is not None
        assert fresh.last_seen_at > old
