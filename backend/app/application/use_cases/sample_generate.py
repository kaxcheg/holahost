from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from application.dto.sample import SampleGenerateCmd, SampleGenerateResult
from application.exceptions import SampleBudgetExhaustedError, payload_validation
from application.ports.embedding import EmbeddingModel
from application.ports.llm import LLMClient
from application.ports.rate import RateLimiter, RateLimitScope
from application.ports.repos import SampleBudgetRepo
from application.ports.uow import UnitOfWork
from application.ports.vector import VectorSearch
from config.config import Settings
from domain.entities.chunk import Chunk
from domain.entities.guest_message import GuestMessage


@dataclass
class SampleGenerateUseCase:
    """Sample-flow generation on the server key under a daily token budget (spec §9.1)."""

    rate: RateLimiter
    sample_budget_repo: SampleBudgetRepo
    embedder: EmbeddingModel
    vector_search: VectorSearch
    llm: LLMClient
    uow: UnitOfWork
    sample_chunks: list[Chunk]
    settings: Settings

    def execute(self, cmd: SampleGenerateCmd) -> SampleGenerateResult:
        """Rate-check, budget pre-check, retrieve, generate (Haiku), then record token usage.

        Budget pre-check and post-update run in two separate short transactions so the DB
        connection is not held during the LLM call (§9.1). The bounded race (overshoot <= N
        concurrent calls * MAX_OUTPUT_TOKENS) is accepted (§10.2).

        Args:
            cmd: The sample-generate command (guest message + ip hash).

        Returns:
            The generated reply text.

        :raises RateLimitExceededError: per-ip cap exceeded (§9.8).
        :raises InvalidPayloadError: the message is empty or too long (§9.0).
        :raises SampleBudgetExhaustedError: the daily token cap is reached (§9.8).
        :raises UpstreamLLMError: the LLM call failed (§9.8).
        """
        with self.uow.transaction():
            self.rate.check_and_increment(RateLimitScope.IP, cmd.ip_hash)
        with payload_validation():
            guest_message = GuestMessage.create(cmd.message)
        today = datetime.now(tz=UTC).date()
        with self.uow.transaction():
            state = self.sample_budget_repo.get_or_create(today)
            if state.is_exhausted(self.settings.sample_budget_daily_cap_tokens):
                reset_at = datetime.combine(
                    today + timedelta(days=1), time.min, tzinfo=UTC
                ).isoformat()
                raise SampleBudgetExhaustedError(reset_at=reset_at)
        query_vec = self.embedder.embed_one(guest_message.text)
        top_chunks = self.vector_search.top_k(
            query=query_vec, chunks=self.sample_chunks, k=self.settings.retrieval_top_k
        )
        reply = self.llm.generate(
            chunks=top_chunks,
            guest_message=guest_message,
            model_id=self.settings.model_id_sample,
            system_prompt=self.settings.system_prompt,
            max_output_tokens=self.settings.max_output_tokens,
            api_key=self.settings.sample_server_api_key,
            is_byok=False,
        )
        dollars = self._estimate_cost(reply.output_tokens)
        with self.uow.transaction():
            state = self.sample_budget_repo.get_or_create_for_update(today)
            state.add_usage(reply.output_tokens, dollars)
            self.sample_budget_repo.save(state)
        return SampleGenerateResult(response_text=reply.text)

    def _estimate_cost(self, output_tokens: int) -> float:
        return output_tokens * self.settings.haiku_output_price_per_mtok / 1_000_000
