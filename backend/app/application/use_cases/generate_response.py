from __future__ import annotations

from dataclasses import dataclass

from application.dto.generate import GenerateResponseCmd, GenerateResponseResult
from application.exceptions import (
    InvalidMagicLinkError,
    NoGuidebookAttachedError,
    magic_link_validation,
    payload_validation,
)
from application.ports.embedding import EmbeddingModel
from application.ports.llm import LLMClient
from application.ports.rate import RateLimiter, RateLimitScope
from application.ports.repos import ChunksRepo, GuidebooksRepo, LeadsRepo
from application.ports.uow import UnitOfWork
from application.ports.vector import VectorSearch
from config.config import Settings
from domain.entities.chunk import Chunk
from domain.entities.guest_message import GuestMessage
from domain.value_objects.magic_link import MagicLink


@dataclass
class GenerateResponseUseCase:
    """Real-flow generation (Sonnet, BYOK) grounded in the lead's guidebook (spec §9.5)."""

    rate: RateLimiter
    leads_repo: LeadsRepo
    guidebooks_repo: GuidebooksRepo
    chunks_repo: ChunksRepo
    embedder: EmbeddingModel
    vector_search: VectorSearch
    llm: LLMClient
    uow: UnitOfWork
    settings: Settings

    def execute(self, cmd: GenerateResponseCmd) -> GenerateResponseResult:
        """Resolve link → guidebook → chunks, generate with BYOK, then bump timestamps.

        The guidebook is determined solely by ``lead.guidebook_id`` after resolve (no id in the
        command). Retrieval and the LLM call run outside the transaction (§9.5). The first resolve
        is an unlocked read (no lock may span the LLM call); after the LLM the write transaction
        re-reads the lead under a row lock (``get_by_magic_link_for_update``, the holder) and
        re-validates the answered-from guidebook is still attached — if it was replaced, deleted, or
        the lead expired during the call, it raises rather than return a reply grounded in a
        superseded guidebook (§9.5 / §9.0).

        Args:
            cmd: The generate command (magic link, BYOK key, message, ip hash).

        Returns:
            The generated reply text.

        :raises RateLimitExceededError: per-ip or per-magic-link cap exceeded (§9.8).
        :raises InvalidMagicLinkError: token empty/invalid, unknown, or expired (§9.8).
        :raises NoGuidebookAttachedError: no guidebook attached, or it was replaced/deleted (or the
            lead expired) during generation — re-validated under lock before returning (§9.5 / §9.8).
        :raises InvalidPayloadError: the message is empty or too long (§9.0).
        :raises InvalidApiKeyError: upstream 401 on the BYOK key (§9.8).
        :raises UpstreamLLMError: upstream 429/5xx (§9.8).
        """
        with self.uow.transaction():
            self.rate.check_and_increment(RateLimitScope.IP, cmd.ip_hash)
        with magic_link_validation():
            magic_link = MagicLink(cmd.magic_link)
        with self.uow.transaction():
            lead = self.leads_repo.get_by_magic_link(magic_link)
            if lead is None:
                raise InvalidMagicLinkError()
            if lead.guidebook_id is None:
                raise NoGuidebookAttachedError()
            self.rate.check_and_increment(RateLimitScope.MAGIC_LINK, str(lead.id))
            guidebook = self.guidebooks_repo.get(lead.guidebook_id)
            if guidebook is None:
                raise NoGuidebookAttachedError()
            chunks: list[Chunk] = self.chunks_repo.list_for_guidebook(guidebook.id)
        with payload_validation():
            guest_message = GuestMessage.create(cmd.message)
        query_vec = self.embedder.embed_one(guest_message.text)
        top_chunks = self.vector_search.top_k(
            query=query_vec, chunks=chunks, k=self.settings.retrieval_top_k
        )
        reply = self.llm.generate(
            chunks=top_chunks,
            guest_message=guest_message,
            model_id=self.settings.model_id_real,
            system_prompt=self.settings.system_prompt,
            max_output_tokens=self.settings.max_output_tokens,
            api_key=cmd.byok,
            is_byok=True,
        )
        # Re-validate under the holder lock before returning: the tx1 gather was unlocked (no lock
        # may span the LLM call), so the guidebook could have been replaced (upload §9.4) or deleted
        # (cleanup §9.6) meanwhile. Guidebooks are immutable-by-id (a replace makes a NEW id), so an
        # id match means the content we answered from is still attached. If the lead expired or the
        # guidebook changed/deleted, reject rather than serve a reply grounded in a superseded
        # guidebook (§9.5 / §9.0); otherwise bump timestamps on the freshly re-read entities.
        with self.uow.transaction():
            fresh_lead = self.leads_repo.get_by_magic_link_for_update(magic_link)
            if fresh_lead is None or fresh_lead.guidebook_id != guidebook.id:
                raise NoGuidebookAttachedError()
            fresh_guidebook = self.guidebooks_repo.get(guidebook.id)
            if fresh_guidebook is None:
                raise NoGuidebookAttachedError()
            fresh_lead.touch()
            fresh_guidebook.touch()
            self.leads_repo.update(fresh_lead)
            self.guidebooks_repo.update(fresh_guidebook)
        return GenerateResponseResult(response_text=reply.text)
