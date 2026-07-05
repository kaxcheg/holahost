from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta

import pytest
from pydantic import SecretStr

from application.dto.sample import SampleGenerateCmd
from application.exceptions import (
    InvalidPayloadError,
    RateLimitExceededError,
    SampleBudgetExhaustedError,
)
from application.ports.rate import RateLimitScope
from application.use_cases.sample_generate import SampleGenerateUseCase
from config.config import Settings
from config.logging import configure_logging
from domain.entities.chunk import Chunk
from domain.entities.generated_reply import GeneratedReply
from domain.entities.sample_budget_state import SampleBudgetState
from domain.value_objects.guidebook_id import GuidebookId
from tests._support.builders import make_chunk
from tests._support.fakes import (
    FakeEmbeddingModel,
    FakeLLMClient,
    FakeRateLimiter,
    FakeSampleBudgetRepo,
    FakeUnitOfWork,
    FakeVectorSearch,
)
from tests._support.settings import make_settings

_CMD = SampleGenerateCmd(message="How do I check in?", ip_hash="h")


def _chunks() -> list[Chunk]:
    gid = GuidebookId.new()
    return [make_chunk(gid, i) for i in range(3)]


def _uc(
    *,
    budget: FakeSampleBudgetRepo | None = None,
    llm: FakeLLMClient | None = None,
    rate: FakeRateLimiter | None = None,
    settings: Settings | None = None,
    chunks: list[Chunk] | None = None,
) -> SampleGenerateUseCase:
    return SampleGenerateUseCase(
        rate=rate or FakeRateLimiter(),
        sample_budget_repo=budget or FakeSampleBudgetRepo(),
        embedder=FakeEmbeddingModel(),
        vector_search=FakeVectorSearch(),
        llm=llm or FakeLLMClient(reply=GeneratedReply.create("answer", 100)),
        uow=FakeUnitOfWork(),
        sample_chunks=chunks if chunks is not None else _chunks(),
        settings=settings or make_settings(),
    )


class TestSampleGenerate:
    def test_happy_path_returns_text_and_records_budget(self) -> None:
        budget = FakeSampleBudgetRepo()
        uc = _uc(
            budget=budget,
            llm=FakeLLMClient(reply=GeneratedReply.create("answer", 100)),
            settings=make_settings(haiku_output_price_per_mtok=1.0),
        )
        res = uc.execute(_CMD)
        assert res.response_text == "answer"
        saved = budget.saved[-1]
        assert saved.output_tokens_used == 100
        assert saved.dollars_spent_est == pytest.approx(100 * 1.0 / 1_000_000)

    def test_budget_exhausted_blocks(self) -> None:
        today = datetime.now(tz=UTC).date()
        state = SampleBudgetState.from_repo(
            day=today, output_tokens_used=200_000, dollars_spent_est=0.2
        )
        llm = FakeLLMClient()
        uc = _uc(
            budget=FakeSampleBudgetRepo({today: state}),
            llm=llm,
            settings=make_settings(sample_budget_daily_cap_tokens=200_000),
        )
        with pytest.raises(SampleBudgetExhaustedError) as exc:
            uc.execute(_CMD)
        expected = datetime.combine(today + timedelta(days=1), time.min, tzinfo=UTC).isoformat()
        assert exc.value.reset_at == expected
        assert llm.calls == []

    def test_empty_message_raises_payload(self) -> None:
        with pytest.raises(InvalidPayloadError):
            _uc().execute(SampleGenerateCmd(message="", ip_hash="h"))

    def test_rate_ip_enforced(self) -> None:
        with pytest.raises(RateLimitExceededError):
            _uc(rate=FakeRateLimiter(raise_on={RateLimitScope.IP})).execute(_CMD)

    def test_llm_called_with_sample_model_and_server_key(self) -> None:
        llm = FakeLLMClient()
        _uc(llm=llm, settings=make_settings(model_id_sample="haiku-x")).execute(_CMD)
        call = llm.calls[-1]
        assert call["model_id"] == "haiku-x"
        api_key = call["api_key"]
        assert isinstance(api_key, SecretStr)
        assert api_key.get_secret_value() == "sk-sample-key"
        assert call["is_byok"] is False

    def test_happy_path_emits_sample_response_completed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging()
        _uc(llm=FakeLLMClient(reply=GeneratedReply.create("answer", 100))).execute(_CMD)
        records = [
            json.loads(line) for line in capsys.readouterr().err.strip().splitlines() if line
        ]
        event = next(r for r in records if r["event"] == "sample_response_completed")
        # §10.5: the sample-budget metric filter reads sample_tokens_used from this event (I-13).
        assert event["sample_tokens_used"] == 100
        assert event["level"] == "INFO"
