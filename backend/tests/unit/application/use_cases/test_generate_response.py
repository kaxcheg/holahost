from __future__ import annotations

import pytest
from pydantic import SecretStr

from application.dto.generate import GenerateResponseCmd
from application.exceptions import (
    InvalidMagicLinkError,
    InvalidPayloadError,
    NoGuidebookAttachedError,
)
from application.ports.rate import RateLimitScope
from application.use_cases.generate_response import GenerateResponseUseCase
from config.config import Settings
from domain.entities.generated_reply import GeneratedReply
from domain.entities.guidebook import Guidebook
from domain.entities.lead import Lead
from domain.value_objects.guidebook_id import GuidebookId
from domain.value_objects.magic_link import MagicLink
from tests._support.builders import make_chunk, make_guidebook, make_lead, make_magic_link
from tests._support.fakes import (
    FakeChunksRepo,
    FakeEmbeddingModel,
    FakeGuidebooksRepo,
    FakeLeadsRepo,
    FakeLLMClient,
    FakeRateLimiter,
    FakeUnitOfWork,
    FakeVectorSearch,
)
from tests._support.settings import make_settings


def _uc(
    leads: FakeLeadsRepo,
    gbs: FakeGuidebooksRepo,
    chunks_repo: FakeChunksRepo,
    *,
    llm: FakeLLMClient | None = None,
    rate: FakeRateLimiter | None = None,
    settings: Settings | None = None,
) -> GenerateResponseUseCase:
    return GenerateResponseUseCase(
        rate=rate or FakeRateLimiter(),
        leads_repo=leads,
        guidebooks_repo=gbs,
        chunks_repo=chunks_repo,
        embedder=FakeEmbeddingModel(),
        vector_search=FakeVectorSearch(),
        llm=llm or FakeLLMClient(reply=GeneratedReply.create("real answer", 50)),
        uow=FakeUnitOfWork(),
        settings=settings or make_settings(),
    )


def _cmd(token: str = "byok-link") -> GenerateResponseCmd:
    return GenerateResponseCmd(
        magic_link=SecretStr(token), byok=SecretStr("sk-byok"), message="Wifi?", ip_hash="h"
    )


class _ExpiredBeforeTouchLeadsRepo(FakeLeadsRepo):
    """tx1 finds the lead (unlocked read); by tx2 a concurrent cleanup expired it, so the locked
    re-read returns None — generate must reject, not serve a reply grounded in the stale snapshot."""

    def get_by_magic_link_for_update(self, magic_link: MagicLink) -> Lead | None:
        return None


class _ReplacedDuringGenLeadsRepo(FakeLeadsRepo):
    """A concurrent upload replaced the guidebook during the LLM call: the locked re-read returns
    the lead now pointing at a different guidebook id, so generate must reject the stale reply."""

    def __init__(self, leads: list[Lead], new_guidebook_id: GuidebookId) -> None:
        super().__init__(leads)
        self._new_id = new_guidebook_id

    def get_by_magic_link_for_update(self, magic_link: MagicLink) -> Lead | None:
        lead = super().get_by_magic_link_for_update(magic_link)
        if lead is not None:
            lead.attach_guidebook(self._new_id)  # concurrent upload repointed to a new guidebook
        return lead


def _wired() -> tuple[Lead, Guidebook, FakeLeadsRepo, FakeGuidebooksRepo, FakeChunksRepo]:
    gb = make_guidebook()
    lead = make_lead(magic_link=make_magic_link("byok-link"), guidebook_id=gb.id)
    chunks = FakeChunksRepo({gb.id: [make_chunk(gb.id, 0)]})
    return lead, gb, FakeLeadsRepo([lead]), FakeGuidebooksRepo([gb]), chunks


class TestGenerateResponse:
    def test_happy_path(self) -> None:
        lead, gb, leads, gbs, chunks = _wired()
        res = _uc(leads, gbs, chunks).execute(_cmd())
        assert res.response_text == "real answer"
        assert gb in gbs.updated
        assert lead in leads.updated

    def test_unknown_link(self) -> None:
        uc = _uc(FakeLeadsRepo(), FakeGuidebooksRepo(), FakeChunksRepo())
        with pytest.raises(InvalidMagicLinkError):
            uc.execute(_cmd("missing"))

    def test_no_guidebook_attached(self) -> None:
        lead = make_lead(magic_link=make_magic_link("byok-link"), guidebook_id=None)
        uc = _uc(FakeLeadsRepo([lead]), FakeGuidebooksRepo(), FakeChunksRepo())
        with pytest.raises(NoGuidebookAttachedError):
            uc.execute(_cmd())

    def test_guidebook_missing_fk_race(self) -> None:
        gb = make_guidebook()
        lead = make_lead(magic_link=make_magic_link("byok-link"), guidebook_id=gb.id)
        uc = _uc(FakeLeadsRepo([lead]), FakeGuidebooksRepo(), FakeChunksRepo())  # gb absent
        with pytest.raises(NoGuidebookAttachedError):
            uc.execute(_cmd())

    def test_empty_message(self) -> None:
        _, _, leads, gbs, chunks = _wired()
        with pytest.raises(InvalidPayloadError):
            _uc(leads, gbs, chunks).execute(
                GenerateResponseCmd(
                    magic_link=SecretStr("byok-link"), byok=SecretStr("k"), message="", ip_hash="h"
                )
            )

    def test_llm_real_model_and_byok(self) -> None:
        _, _, leads, gbs, chunks = _wired()
        llm = FakeLLMClient()
        _uc(leads, gbs, chunks, llm=llm, settings=make_settings(model_id_real="sonnet-x")).execute(
            _cmd()
        )
        call = llm.calls[-1]
        assert call["model_id"] == "sonnet-x"
        api_key = call["api_key"]
        assert isinstance(api_key, SecretStr)
        assert api_key.get_secret_value() == "sk-byok"
        assert call["is_byok"] is True

    def test_rate_subjects(self) -> None:
        lead, _, leads, gbs, chunks = _wired()
        rate = FakeRateLimiter()
        _uc(leads, gbs, chunks, rate=rate).execute(_cmd())
        assert (RateLimitScope.IP, "h") in rate.calls
        assert (RateLimitScope.MAGIC_LINK, str(lead.id)) in rate.calls

    def test_concurrent_expire_rejects_without_serving_stale(self) -> None:
        # Lead expired between the tx1 read and the tx2 locked re-read → reject (no stale reply,
        # no write), never a silently-served snapshot.
        lead, _gb, _, gbs, chunks = _wired()
        leads = _ExpiredBeforeTouchLeadsRepo([lead])
        with pytest.raises(NoGuidebookAttachedError):
            _uc(leads, gbs, chunks).execute(_cmd())
        assert leads.updated == []
        assert gbs.updated == []

    def test_guidebook_replaced_mid_generation_rejects(self) -> None:
        # A concurrent upload swapped the guidebook (new id) during the LLM call → reject; never
        # serve a reply grounded in the now-superseded guidebook.
        lead, _gb, _, gbs, chunks = _wired()
        new_guidebook_id = make_guidebook().id
        leads = _ReplacedDuringGenLeadsRepo([lead], new_guidebook_id)
        with pytest.raises(NoGuidebookAttachedError):
            _uc(leads, gbs, chunks).execute(_cmd())
        assert leads.updated == []
