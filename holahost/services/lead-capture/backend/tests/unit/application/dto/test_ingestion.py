from pydantic import SecretStr

from application.dto.ingestion import IngestionResult, UploadGuidebookCmd


class TestUploadGuidebookCmd:
    def test_magic_link_masked(self) -> None:
        cmd = UploadGuidebookCmd(
            magic_link=SecretStr("tok"),
            ip_hash="a" * 64,
            name="Villa",
            file_bytes=b"%PDF",
            mime_type="application/pdf",
        )
        assert "tok" not in repr(cmd)
        assert cmd.file_bytes == b"%PDF"


class TestIngestionResult:
    def test_fields(self) -> None:
        r = IngestionResult(guidebook_id="id", name="Villa", created_at="2026-06-10T00:00:00+00:00")
        assert r.name == "Villa"
