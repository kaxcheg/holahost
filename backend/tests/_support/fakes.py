"""In-memory fakes for the application ports (reused across application/infra unit tests).

``FakeUnitOfWork`` tracks ``commits``/``rollbacks`` and re-raises on error; it does NOT snapshot
or restore state — real transactional rollback is integration-tested at the Postgres UoW (B-31).
Tests assert "did/did not commit" via the counters, not store reversion.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import date, datetime

from pydantic import SecretStr

from application.exceptions import RateLimitExceededError
from application.ports.rate import RateLimitScope
from domain.entities.chunk import Chunk
from domain.entities.generated_reply import GeneratedReply
from domain.entities.guest_message import GuestMessage
from domain.entities.guidebook import Guidebook
from domain.entities.lead import Lead
from domain.entities.sample_budget_state import SampleBudgetState
from domain.value_objects.email import Email
from domain.value_objects.embedding import Embedding
from domain.value_objects.guidebook_id import GuidebookId
from domain.value_objects.lead_id import LeadId
from domain.value_objects.magic_link import MagicLink
from domain.value_objects.parsed_segment import ParsedSegment
from tests._support.builders import make_embedding


class FakeUnitOfWork:
    """In-memory UoW that counts commits/rollbacks and re-raises on error."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def transaction(self) -> AbstractContextManager[None]:
        return self._txn()

    @contextmanager
    def _txn(self) -> Iterator[None]:
        try:
            yield
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1


class FakeRateLimiter:
    """Records calls; optionally raises on configured scopes; returns a fixed cleanup count."""

    def __init__(
        self, raise_on: set[RateLimitScope] | None = None, cleanup_deleted: int = 0
    ) -> None:
        self.calls: list[tuple[RateLimitScope, str]] = []
        self._raise_on = raise_on or set()
        self._cleanup_deleted = cleanup_deleted
        self.cleanup_calls: list[datetime] = []

    def check_and_increment(self, scope: RateLimitScope, subject: str) -> None:
        self.calls.append((scope, subject))
        if scope in self._raise_on:
            raise RateLimitExceededError(scope=scope.value, retry_after_seconds=60)

    def cleanup_old_windows(self, threshold: datetime) -> int:
        self.cleanup_calls.append(threshold)
        return self._cleanup_deleted


class FakeLeadsRepo:
    """In-memory ``LeadsRepo`` keyed by lead id, with email/magic-link lookups."""

    def __init__(self, leads: list[Lead] | None = None) -> None:
        self._by_id: dict[LeadId, Lead] = {lead.id: lead for lead in (leads or [])}
        self.added: list[Lead] = []
        self.updated: list[Lead] = []

    def get_by_id(self, id: LeadId) -> Lead | None:
        """Off-Protocol test-introspection helper: plain read (no simulated lock side-effects)."""
        return self._by_id.get(id)

    def get_by_id_for_update(self, id: LeadId) -> Lead | None:
        return self._by_id.get(id)

    def get_by_email_for_update(self, email: Email) -> Lead | None:
        return next((lead for lead in self._by_id.values() if lead.email == email), None)

    def get_by_magic_link(self, magic_link: MagicLink) -> Lead | None:
        return self._find_by_magic_link(magic_link)

    def get_by_magic_link_for_update(self, magic_link: MagicLink) -> Lead | None:
        return self._find_by_magic_link(magic_link)

    def _find_by_magic_link(self, magic_link: MagicLink) -> Lead | None:
        return next(
            (
                lead
                for lead in self._by_id.values()
                if lead.magic_link is not None and lead.magic_link == magic_link
            ),
            None,
        )

    def add(self, lead: Lead) -> None:
        self._by_id[lead.id] = lead
        self.added.append(lead)

    def update(self, lead: Lead) -> None:
        self._by_id[lead.id] = lead
        self.updated.append(lead)

    def list_expired(self, threshold: datetime, limit: int) -> list[Lead]:
        return [
            lead
            for lead in self._by_id.values()
            if lead.magic_link is not None and lead.last_seen_at < threshold
        ][:limit]


class FakeGuidebooksRepo:
    """In-memory ``GuidebooksRepo`` keyed by guidebook id."""

    def __init__(self, guidebooks: list[Guidebook] | None = None) -> None:
        self._by_id: dict[GuidebookId, Guidebook] = {gb.id: gb for gb in (guidebooks or [])}
        self.added: list[Guidebook] = []
        self.deleted: list[GuidebookId] = []
        self.updated: list[Guidebook] = []

    def get(self, guidebook_id: GuidebookId) -> Guidebook | None:
        return self._by_id.get(guidebook_id)

    def add(self, guidebook: Guidebook) -> None:
        self._by_id[guidebook.id] = guidebook
        self.added.append(guidebook)

    def delete(self, guidebook_id: GuidebookId) -> None:
        self._by_id.pop(guidebook_id, None)
        self.deleted.append(guidebook_id)

    def update(self, guidebook: Guidebook) -> None:
        self._by_id[guidebook.id] = guidebook
        self.updated.append(guidebook)


class FakeChunksRepo:
    """In-memory ``ChunksRepo`` keyed by guidebook id."""

    def __init__(self, chunks_by_gb: dict[GuidebookId, list[Chunk]] | None = None) -> None:
        self._by_gb: dict[GuidebookId, list[Chunk]] = dict(chunks_by_gb or {})
        self.bulk_added: list[list[Chunk]] = []

    def list_for_guidebook(self, guidebook_id: GuidebookId) -> list[Chunk]:
        return list(self._by_gb.get(guidebook_id, []))

    def bulk_add(self, chunks: list[Chunk]) -> None:
        self.bulk_added.append(chunks)
        for chunk in chunks:
            self._by_gb.setdefault(chunk.guidebook_id, []).append(chunk)


class FakeSampleBudgetRepo:
    """In-memory ``SampleBudgetRepo`` keyed by day."""

    def __init__(self, states: dict[date, SampleBudgetState] | None = None) -> None:
        self._by_day: dict[date, SampleBudgetState] = dict(states or {})
        self.saved: list[SampleBudgetState] = []

    def get_or_create(self, day: date) -> SampleBudgetState:
        if day not in self._by_day:
            self._by_day[day] = SampleBudgetState.create(day)
        return self._by_day[day]

    def get_or_create_for_update(self, day: date) -> SampleBudgetState:
        return self.get_or_create(day)

    def save(self, state: SampleBudgetState) -> None:
        self._by_day[state.day] = state
        self.saved.append(state)


class FakeEmbeddingModel:
    """Deterministic ``EmbeddingModel`` returning valid one-hot embeddings."""

    def __init__(self) -> None:
        self.embed_one_calls: list[str] = []
        self.embed_many_calls: list[list[str]] = []

    def embed_one(self, text: str) -> Embedding:
        self.embed_one_calls.append(text)
        return make_embedding()

    def embed_many(self, texts: list[str]) -> list[Embedding]:
        self.embed_many_calls.append(texts)
        return [make_embedding(i) for i, _ in enumerate(texts)]


class FakeVectorSearch:
    """``VectorSearch`` returning the first ``k`` candidate chunks."""

    def __init__(self) -> None:
        self.calls: list[tuple[Embedding, list[Chunk], int]] = []

    def top_k(self, query: Embedding, chunks: list[Chunk], k: int) -> list[Chunk]:
        self.calls.append((query, chunks, k))
        return list(chunks)[:k]


class FakeLLMClient:
    """``LLMClient`` returning a canned reply, or raising a configured error."""

    def __init__(self, reply: GeneratedReply | None = None, error: Exception | None = None) -> None:
        self.reply = reply if reply is not None else GeneratedReply.create("stub reply", 10)
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        chunks: list[Chunk],
        guest_message: GuestMessage,
        model_id: str,
        system_prompt: str,
        max_output_tokens: int,
        api_key: SecretStr,
        is_byok: bool,
    ) -> GeneratedReply:
        self.calls.append(
            {
                "chunks": chunks,
                "guest_message": guest_message,
                "model_id": model_id,
                "system_prompt": system_prompt,
                "max_output_tokens": max_output_tokens,
                "api_key": api_key,
                "is_byok": is_byok,
            }
        )
        if self.error is not None:
            raise self.error
        return self.reply


class FakeEmailSender:
    """``EmailSender`` recording sends, or raising a configured error."""

    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[tuple[Email, MagicLink]] = []
        self.error = error

    def send_magic_link(self, to: Email, magic_link: MagicLink) -> None:
        self.sent.append((to, magic_link))
        if self.error is not None:
            raise self.error


class FakeMagicLinkGenerator:
    """``MagicLinkGenerator`` issuing sequential, distinct tokens."""

    def __init__(self, token: str = "generated") -> None:
        self._token = token
        self.count = 0

    def generate(self) -> MagicLink:
        self.count += 1
        return MagicLink(value=SecretStr(f"{self._token}-{self.count}"))


class FakeFileParser:
    """``FileParser`` returning a single fixed segment (``page=None``)."""

    def __init__(self, text: str = "parsed document text") -> None:
        self.text = text
        self.calls: list[tuple[bytes, str]] = []

    def parse(self, file_bytes: bytes, mime_type: str) -> list[ParsedSegment]:
        self.calls.append((file_bytes, mime_type))
        return [ParsedSegment(text=self.text, page=None)]


class FakeTextChunker:
    """``TextChunker`` returning fixed chunks; optional per-chunk ``pages`` for provenance tests."""

    def __init__(
        self, chunks: list[str] | None = None, pages: list[int | None] | None = None
    ) -> None:
        self.chunks = chunks if chunks is not None else ["chunk-0", "chunk-1"]
        self.pages = pages
        self.calls: list[list[ParsedSegment]] = []

    def chunk(self, segments: list[ParsedSegment]) -> list[ParsedSegment]:
        self.calls.append(segments)
        if self.pages is not None:
            return [
                ParsedSegment(text=t, page=p)
                for t, p in zip(self.chunks, self.pages, strict=True)
            ]
        return [ParsedSegment(text=t, page=None) for t in self.chunks]
