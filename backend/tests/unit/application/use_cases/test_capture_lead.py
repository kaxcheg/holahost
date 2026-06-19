from __future__ import annotations

import pytest

from application.dto.leads import CaptureLeadCmd
from application.exceptions import (
    InvalidPayloadError,
    RateLimitExceededError,
    UpstreamEmailError,
)
from application.ports.rate import RateLimitScope
from application.use_cases.capture_lead import CaptureLeadUseCase
from domain.value_objects.email import Email
from tests._support.builders import make_lead
from tests._support.fakes import (
    FakeEmailSender,
    FakeLeadsRepo,
    FakeMagicLinkGenerator,
    FakeRateLimiter,
    FakeUnitOfWork,
)
from tests._support.settings import make_settings

_IP = "0123456789abcdef" * 4  # valid 64-hex ip hash (IpHash invariant, §7.2.3)
_CMD = CaptureLeadCmd(email="new@example.com", flow="guidebook", ip_hash=_IP, ua_short="UA")


def _uc(
    leads: FakeLeadsRepo,
    *,
    email: FakeEmailSender | None = None,
    rate: FakeRateLimiter | None = None,
    gen: FakeMagicLinkGenerator | None = None,
    uow: FakeUnitOfWork | None = None,
) -> CaptureLeadUseCase:
    return CaptureLeadUseCase(
        rate=rate or FakeRateLimiter(),
        leads_repo=leads,
        email_sender=email or FakeEmailSender(),
        magic_link_gen=gen or FakeMagicLinkGenerator(),
        uow=uow or FakeUnitOfWork(),
        settings=make_settings(),
    )


class TestCaptureLead:
    def test_new_email_creates_lead_and_sends(self) -> None:
        leads = FakeLeadsRepo()
        sender = FakeEmailSender()
        _uc(leads, email=sender).execute(_CMD)
        assert len(leads.added) == 1
        assert leads.added[0].email == Email("new@example.com")
        assert len(sender.sent) == 1

    def test_existing_email_regenerates_link(self) -> None:
        existing = make_lead(email="dup@example.com")
        leads = FakeLeadsRepo([existing])
        _uc(leads).execute(
            CaptureLeadCmd(email="dup@example.com", flow="sample", ip_hash=_IP, ua_short=None)
        )
        assert leads.added == []
        assert len(leads.updated) == 1
        assert leads.updated[0].id == existing.id

    def test_honeypot_rejected_before_side_effects(self) -> None:
        leads = FakeLeadsRepo()
        rate = FakeRateLimiter()
        sender = FakeEmailSender()
        uc = _uc(leads, email=sender, rate=rate)
        with pytest.raises(InvalidPayloadError) as exc:
            uc.execute(
                CaptureLeadCmd(
                    email="x@y.co", flow="guidebook", ip_hash=_IP, ua_short=None, honeypot="bot"
                )
            )
        assert exc.value.reason == "honeypot"
        assert rate.calls == []
        assert leads.added == []
        assert sender.sent == []

    def test_invalid_email_raises_payload(self) -> None:
        with pytest.raises(InvalidPayloadError):
            _uc(FakeLeadsRepo()).execute(
                CaptureLeadCmd(email="not-an-email", flow="guidebook", ip_hash=_IP, ua_short=None)
            )

    def test_invalid_flow_raises_payload(self) -> None:
        with pytest.raises(InvalidPayloadError) as exc:
            _uc(FakeLeadsRepo()).execute(
                CaptureLeadCmd(email="ok@example.com", flow="bogus", ip_hash=_IP, ua_short=None)
            )
        assert exc.value.field == "flow"

    def test_resend_failure_rolls_back(self) -> None:
        uow = FakeUnitOfWork()
        sender = FakeEmailSender(error=UpstreamEmailError(retryable=True))
        with pytest.raises(UpstreamEmailError):
            _uc(FakeLeadsRepo(), email=sender, uow=uow).execute(_CMD)
        assert uow.rollbacks == 1  # business tx rolled back (lead/email not persisted)
        assert uow.commits == 1  # IP rate-check tx committed independently (attempt counted)

    def test_rate_ip_enforced(self) -> None:
        uc = _uc(FakeLeadsRepo(), rate=FakeRateLimiter(raise_on={RateLimitScope.IP}))
        with pytest.raises(RateLimitExceededError):
            uc.execute(_CMD)
