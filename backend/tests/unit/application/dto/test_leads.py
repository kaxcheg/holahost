from pydantic import SecretStr

from application.dto.leads import CaptureLeadCmd, ResolveMagicLinkCmd, ResolveMagicLinkResult


class TestCaptureLeadCmd:
    def test_fields(self) -> None:
        cmd = CaptureLeadCmd(email="a@b.co", flow="sample", ip_hash="a" * 64, ua_short=None)
        assert cmd.flow == "sample"
        assert cmd.ua_short is None


class TestResolveMagicLinkCmd:
    def test_magic_link_is_secret_and_masked(self) -> None:
        cmd = ResolveMagicLinkCmd(magic_link=SecretStr("tok-123"), ip_hash="a" * 64)
        assert "tok-123" not in repr(cmd)
        assert cmd.magic_link.get_secret_value() == "tok-123"

    def test_frozen(self) -> None:
        import dataclasses

        import pytest

        cmd = ResolveMagicLinkCmd(magic_link=SecretStr("x"), ip_hash="a" * 64)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.ip_hash = "b"  # type: ignore[misc]


class TestResolveMagicLinkResult:
    def test_nullable_fields(self) -> None:
        r = ResolveMagicLinkResult(
            email="a@b.co",
            flow="guidebook",
            guidebook_id=None,
            guidebook_name=None,
            guidebook_created_at=None,
        )
        assert r.guidebook_id is None
