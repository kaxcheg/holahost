from __future__ import annotations

import pytest
from pydantic import SecretStr

from application.dto.ingestion import UploadGuidebookCmd
from application.exceptions import (
    EmptyDocumentError,
    InvalidMagicLinkError,
    InvalidPayloadError,
    PayloadTooLargeError,
    RateLimitExceededError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
)
from application.ports.rate import RateLimitScope
from application.use_cases.upload_guidebook import UploadGuidebookUseCase
from config.config import Settings
from domain.entities.lead import Lead
from domain.value_objects.guidebook_id import GuidebookId
from tests._support.builders import make_guidebook, make_lead, make_magic_link
from tests._support.fakes import (
    FakeChunksRepo,
    FakeEmbeddingModel,
    FakeFileParser,
    FakeGuidebooksRepo,
    FakeLeadsRepo,
    FakeRateLimiter,
    FakeTextChunker,
    FakeUnitOfWork,
)
from tests._support.settings import make_settings

_IP = "0123456789abcdef" * 4  # valid 64-hex ip hash


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = dict(
        max_upload_size_bytes=1000,
        allowed_mime_types=frozenset({"text/plain"}),
        min_extracted_text_chars=10,
        max_chunks_per_guidebook=500,
    )
    base.update(overrides)
    return make_settings(**base)


def _uc(
    leads: FakeLeadsRepo,
    gbs: FakeGuidebooksRepo,
    chunks_repo: FakeChunksRepo,
    *,
    parser: FakeFileParser | None = None,
    chunker: FakeTextChunker | None = None,
    rate: FakeRateLimiter | None = None,
    settings: Settings | None = None,
) -> UploadGuidebookUseCase:
    return UploadGuidebookUseCase(
        rate=rate or FakeRateLimiter(),
        leads_repo=leads,
        guidebooks_repo=gbs,
        chunks_repo=chunks_repo,
        parser=parser or FakeFileParser("x" * 100),
        chunker=chunker or FakeTextChunker(["a", "b"]),
        embedder=FakeEmbeddingModel(),
        uow=FakeUnitOfWork(),
        settings=settings or _settings(),
    )


def _cmd(
    *, name: str = "My Place", mime: str = "text/plain", data: bytes = b"hello"
) -> UploadGuidebookCmd:
    return UploadGuidebookCmd(
        magic_link=SecretStr("up-link"), ip_hash=_IP, name=name, file_bytes=data, mime_type=mime
    )


def _wired(*, guidebook_id: GuidebookId | None = None) -> tuple[Lead, FakeLeadsRepo]:
    lead = make_lead(magic_link=make_magic_link("up-link"), guidebook_id=guidebook_id)
    return lead, FakeLeadsRepo([lead])


class TestUploadGuidebook:
    def test_first_upload_creates_and_attaches(self) -> None:
        created_lead, leads = _wired()
        gbs = FakeGuidebooksRepo()
        chunks = FakeChunksRepo()
        res = _uc(leads, gbs, chunks).execute(_cmd(name="Riverside"))
        assert res.name == "Riverside"
        assert len(gbs.added) == 1
        assert len(chunks.bulk_added) == 1
        fresh = leads.get_by_id(created_lead.id)
        assert fresh is not None
        assert fresh.guidebook_id == gbs.added[0].id

    def test_replace_deletes_old(self) -> None:
        old = make_guidebook()
        _, leads = _wired(guidebook_id=old.id)
        gbs = FakeGuidebooksRepo([old])
        res = _uc(leads, gbs, FakeChunksRepo()).execute(_cmd())
        assert old.id in gbs.deleted
        assert res.guidebook_id != str(old.id)

    def test_payload_too_large_bytes(self) -> None:
        _, leads = _wired()
        uc = _uc(
            leads,
            FakeGuidebooksRepo(),
            FakeChunksRepo(),
            settings=_settings(max_upload_size_bytes=5),
        )
        with pytest.raises(PayloadTooLargeError):
            uc.execute(_cmd(data=b"way too many bytes"))

    def test_too_small_bytes(self) -> None:
        _, leads = _wired()
        uc = _uc(
            leads,
            FakeGuidebooksRepo(),
            FakeChunksRepo(),
            settings=_settings(min_upload_size_bytes=10),
        )
        with pytest.raises(EmptyDocumentError):
            uc.execute(_cmd(data=b"hi"))

    def test_unsupported_media_type(self) -> None:
        _, leads = _wired()
        with pytest.raises(UnsupportedMediaTypeError):
            _uc(leads, FakeGuidebooksRepo(), FakeChunksRepo()).execute(_cmd(mime="image/png"))

    def test_empty_name(self) -> None:
        _, leads = _wired()
        with pytest.raises(InvalidPayloadError) as exc:
            _uc(leads, FakeGuidebooksRepo(), FakeChunksRepo()).execute(_cmd(name="  "))
        assert exc.value.reason == "empty"

    def test_empty_document(self) -> None:
        _, leads = _wired()
        uc = _uc(
            leads,
            FakeGuidebooksRepo(),
            FakeChunksRepo(),
            parser=FakeFileParser("short"),
            settings=_settings(min_extracted_text_chars=100),
        )
        with pytest.raises(EmptyDocumentError):
            uc.execute(_cmd())

    def test_too_many_chunks(self) -> None:
        _, leads = _wired()
        uc = _uc(
            leads,
            FakeGuidebooksRepo(),
            FakeChunksRepo(),
            chunker=FakeTextChunker(["c"] * 600),
            settings=_settings(min_extracted_text_chars=1, max_chunks_per_guidebook=500),
        )
        with pytest.raises(TooManyChunksError) as exc:
            uc.execute(_cmd())
        assert exc.value.max_chunks == 500

    def test_too_few_chunks(self) -> None:
        _, leads = _wired()
        uc = _uc(
            leads,
            FakeGuidebooksRepo(),
            FakeChunksRepo(),
            chunker=FakeTextChunker([]),
            settings=_settings(min_extracted_text_chars=1, min_chunks_per_guidebook=1),
        )
        with pytest.raises(EmptyDocumentError):
            uc.execute(_cmd())

    def test_unknown_link(self) -> None:
        with pytest.raises(InvalidMagicLinkError):
            _uc(FakeLeadsRepo(), FakeGuidebooksRepo(), FakeChunksRepo()).execute(_cmd())

    def test_rate_ip_first(self) -> None:
        _, leads = _wired()
        rate = FakeRateLimiter(raise_on={RateLimitScope.IP})
        with pytest.raises(RateLimitExceededError):
            _uc(leads, FakeGuidebooksRepo(), FakeChunksRepo(), rate=rate).execute(_cmd())
        assert rate.calls[0] == (RateLimitScope.IP, _IP)
