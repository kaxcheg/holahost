from datetime import UTC, datetime

from domain.entities.guidebook import Guidebook
from domain.value_objects.guidebook_id import GuidebookId
from domain.value_objects.guidebook_name import GuidebookName
from domain.value_objects.ip_hash import IpHash

_IP = IpHash("0123456789abcdef" * 4)
_IP2 = IpHash("fedcba9876543210" * 4)
_T = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


class TestGuidebook:
    def test_create_sets_fields_and_timestamps(self) -> None:
        gb = Guidebook.create(name=GuidebookName("My Place"), ip_hash=_IP)
        assert isinstance(gb.id, GuidebookId)
        assert gb.name == GuidebookName("My Place")
        assert gb.ip_hash == _IP
        assert gb.created_at == gb.last_accessed_at
        assert gb.created_at.tzinfo is UTC

    def test_create_generates_unique_ids(self) -> None:
        ids = {Guidebook.create(name=GuidebookName("n"), ip_hash=_IP).id for _ in range(100)}
        assert len(ids) == 100

    def test_from_repo_reconstructs_verbatim(self) -> None:
        gid = GuidebookId.new()
        gb = Guidebook.from_repo(
            id=gid, name=GuidebookName("Loaded"), created_at=_T, last_accessed_at=_T, ip_hash=_IP
        )
        assert gb.id == gid
        assert gb.name == GuidebookName("Loaded")
        assert gb.created_at == _T
        assert gb.last_accessed_at == _T
        assert gb.ip_hash == _IP

    def test_touch_advances_last_accessed_at(self) -> None:
        gb = Guidebook.from_repo(
            id=GuidebookId.new(),
            name=GuidebookName("n"),
            created_at=_T,
            last_accessed_at=_T,
            ip_hash=_IP,
        )
        gb.touch()
        assert gb.last_accessed_at > _T
        assert gb.last_accessed_at.tzinfo is UTC
        assert gb.created_at == _T  # unchanged

    def test_equal_when_same_id_regardless_of_other_fields(self) -> None:
        gid = GuidebookId.new()
        a = Guidebook.from_repo(
            id=gid, name=GuidebookName("A"), created_at=_T, last_accessed_at=_T, ip_hash=_IP
        )
        b = Guidebook.from_repo(
            id=gid, name=GuidebookName("B"), created_at=_T, last_accessed_at=_T, ip_hash=_IP2
        )
        assert a == b

    def test_not_equal_when_different_id_or_other_type(self) -> None:
        a = Guidebook.create(name=GuidebookName("A"), ip_hash=_IP)
        b = Guidebook.create(name=GuidebookName("A"), ip_hash=_IP)
        assert a != b  # independently generated ids differ
        not_a_guidebook: object = "not-a-guidebook"
        assert a != not_a_guidebook

    def test_hashable_by_id(self) -> None:
        gid = GuidebookId.new()
        a = Guidebook.from_repo(
            id=gid, name=GuidebookName("A"), created_at=_T, last_accessed_at=_T, ip_hash=_IP
        )
        b = Guidebook.from_repo(
            id=gid, name=GuidebookName("B"), created_at=_T, last_accessed_at=_T, ip_hash=_IP2
        )
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
