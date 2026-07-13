from datetime import UTC, datetime

from pydantic import SecretStr

from domain.entities.lead import Lead
from domain.value_objects.email import Email
from domain.value_objects.guidebook_id import GuidebookId
from domain.value_objects.ip_hash import IpHash
from domain.value_objects.lead_flow import LeadFlow
from domain.value_objects.lead_id import LeadId
from domain.value_objects.magic_link import MagicLink

_EMAIL = Email("host@example.com")
_ML = MagicLink(value=SecretStr("abc123token"))
_IP = IpHash("0123456789abcdef" * 4)
_IP2 = IpHash("fedcba9876543210" * 4)
_GID = GuidebookId.new()
_T = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


class TestLead:
    def test_create_sets_fields(self) -> None:
        lead = Lead.create(
            email=_EMAIL, magic_link=_ML, flow=LeadFlow.GUIDEBOOK, ip_hash=_IP, ua_short="Mozilla"
        )
        assert isinstance(lead.id, LeadId)
        assert lead.email == _EMAIL
        assert lead.magic_link == _ML
        assert lead.flow == LeadFlow.GUIDEBOOK
        assert lead.ip_hash == _IP
        assert lead.ua_short == "Mozilla"
        assert lead.guidebook_id is None
        assert lead.captured_at == lead.last_seen_at
        assert lead.captured_at.tzinfo is UTC

    def test_create_accepts_none_ua_short(self) -> None:
        lead = Lead.create(
            email=_EMAIL, magic_link=_ML, flow=LeadFlow.SAMPLE, ip_hash=_IP, ua_short=None
        )
        assert lead.ua_short is None

    def test_create_generates_unique_ids(self) -> None:
        ids = {
            Lead.create(
                email=_EMAIL, magic_link=_ML, flow=LeadFlow.GUIDEBOOK, ip_hash=_IP, ua_short=None
            ).id
            for _ in range(100)
        }
        assert len(ids) == 100

    def test_from_repo_reconstructs_verbatim(self) -> None:
        lid = LeadId.new()
        lead = Lead.from_repo(
            id=lid,
            email=_EMAIL,
            magic_link=_ML,
            captured_at=_T,
            last_seen_at=_T,
            flow=LeadFlow.GUIDEBOOK,
            guidebook_id=_GID,
            ip_hash=_IP,
            ua_short="curl",
        )
        assert lead.id == lid
        assert lead.email == _EMAIL
        assert lead.magic_link == _ML
        assert lead.captured_at == _T
        assert lead.last_seen_at == _T
        assert lead.flow == LeadFlow.GUIDEBOOK
        assert lead.guidebook_id == _GID
        assert lead.ip_hash == _IP
        assert lead.ua_short == "curl"

    def test_from_repo_allows_none_magic_link_and_guidebook_id(self) -> None:
        lead = Lead.from_repo(
            id=LeadId.new(),
            email=_EMAIL,
            magic_link=None,
            captured_at=_T,
            last_seen_at=_T,
            flow=LeadFlow.SAMPLE,
            guidebook_id=None,
            ip_hash=_IP,
            ua_short=None,
        )
        assert lead.magic_link is None
        assert lead.guidebook_id is None

    def test_regenerate_magic_link_updates_fields(self) -> None:
        lead = Lead.from_repo(
            id=LeadId.new(),
            email=_EMAIL,
            magic_link=_ML,
            captured_at=_T,
            last_seen_at=_T,
            flow=LeadFlow.GUIDEBOOK,
            guidebook_id=None,
            ip_hash=_IP,
            ua_short=None,
        )
        new_ml = MagicLink(value=SecretStr("newtoken456"))
        lead.regenerate_magic_link(new_ml)
        assert lead.magic_link == new_ml
        assert lead.last_seen_at > _T
        assert lead.last_seen_at.tzinfo is UTC
        assert lead.captured_at == _T

    def test_attach_guidebook_sets_guidebook_id_and_last_seen_at(self) -> None:
        lead = Lead.from_repo(
            id=LeadId.new(),
            email=_EMAIL,
            magic_link=_ML,
            captured_at=_T,
            last_seen_at=_T,
            flow=LeadFlow.GUIDEBOOK,
            guidebook_id=None,
            ip_hash=_IP,
            ua_short=None,
        )
        gid = GuidebookId.new()
        lead.attach_guidebook(gid)
        assert lead.guidebook_id == gid
        assert lead.last_seen_at > _T
        assert lead.last_seen_at.tzinfo is UTC
        assert lead.captured_at == _T

    def test_detach_guidebook_clears_guidebook_id(self) -> None:
        lead = Lead.from_repo(
            id=LeadId.new(),
            email=_EMAIL,
            magic_link=_ML,
            captured_at=_T,
            last_seen_at=_T,
            flow=LeadFlow.GUIDEBOOK,
            guidebook_id=_GID,
            ip_hash=_IP,
            ua_short=None,
        )
        lead.detach_guidebook()
        assert lead.guidebook_id is None
        assert lead.last_seen_at == _T  # detach is cleanup, not activity — must not advance TTL

    def test_touch_advances_last_seen_at(self) -> None:
        lead = Lead.from_repo(
            id=LeadId.new(),
            email=_EMAIL,
            magic_link=_ML,
            captured_at=_T,
            last_seen_at=_T,
            flow=LeadFlow.GUIDEBOOK,
            guidebook_id=None,
            ip_hash=_IP,
            ua_short=None,
        )
        lead.touch()
        assert lead.last_seen_at > _T
        assert lead.last_seen_at.tzinfo is UTC
        assert lead.captured_at == _T

    def test_expire_magic_link_sets_magic_link_to_none(self) -> None:
        lead = Lead.from_repo(
            id=LeadId.new(),
            email=_EMAIL,
            magic_link=_ML,
            captured_at=_T,
            last_seen_at=_T,
            flow=LeadFlow.GUIDEBOOK,
            guidebook_id=None,
            ip_hash=_IP,
            ua_short=None,
        )
        lead.expire_magic_link()
        assert lead.magic_link is None

    def test_equal_when_same_id_regardless_of_other_fields(self) -> None:
        lid = LeadId.new()
        a = Lead.from_repo(
            id=lid,
            email=_EMAIL,
            magic_link=_ML,
            captured_at=_T,
            last_seen_at=_T,
            flow=LeadFlow.GUIDEBOOK,
            guidebook_id=None,
            ip_hash=_IP,
            ua_short=None,
        )
        b = Lead.from_repo(
            id=lid,
            email=Email("other@example.com"),
            magic_link=None,
            captured_at=_T,
            last_seen_at=_T,
            flow=LeadFlow.SAMPLE,
            guidebook_id=_GID,
            ip_hash=_IP2,
            ua_short="agent",
        )
        assert a == b

    def test_not_equal_when_different_id_or_other_type(self) -> None:
        a = Lead.create(
            email=_EMAIL, magic_link=_ML, flow=LeadFlow.GUIDEBOOK, ip_hash=_IP, ua_short=None
        )
        b = Lead.create(
            email=_EMAIL, magic_link=_ML, flow=LeadFlow.GUIDEBOOK, ip_hash=_IP, ua_short=None
        )
        assert a != b
        not_a_lead: object = "not-a-lead"
        assert a != not_a_lead

    def test_hashable_by_id(self) -> None:
        lid = LeadId.new()
        a = Lead.from_repo(
            id=lid,
            email=_EMAIL,
            magic_link=_ML,
            captured_at=_T,
            last_seen_at=_T,
            flow=LeadFlow.GUIDEBOOK,
            guidebook_id=None,
            ip_hash=_IP,
            ua_short=None,
        )
        b = Lead.from_repo(
            id=lid,
            email=Email("other@example.com"),
            magic_link=None,
            captured_at=_T,
            last_seen_at=_T,
            flow=LeadFlow.SAMPLE,
            guidebook_id=_GID,
            ip_hash=_IP2,
            ua_short="agent",
        )
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
