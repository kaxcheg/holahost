from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from application.dto.cleanup import CleanupResult
from application.ports.repos import GuidebooksRepo, LeadsRepo
from application.ports.uow import UnitOfWork
from config.config import Settings


@dataclass
class CleanupExpiredUseCase:
    """Soft-expire over-TTL magic links and delete their guidebooks (spec §9.6; cleanup-Lambda)."""

    leads_repo: LeadsRepo
    guidebooks_repo: GuidebooksRepo
    uow: UnitOfWork
    settings: Settings

    def execute(self) -> CleanupResult:
        """Expire every lead with a non-null magic link and ``last_seen_at`` past the TTL.

        Reads candidates in short batches, then processes each lead in its own transaction. The
        lead (aggregate holder) is re-read FIRST under a row lock (``get_by_id_for_update``); the
        lock is held to commit, so a concurrent ``/resolve`` / ``/generate`` ``touch`` cannot
        interleave between the re-check and the expire. Guidebook deletion and magic-link expiry are
        tracked independently.

        Concurrency: per-lead ``SELECT ... FOR UPDATE`` (§9.0) — brief, intra-transaction, NOT held
        across the batch loop (the candidate ``list_expired`` read is unlocked). The re-check after
        the locked read still skips a lead a concurrent ``touch`` extended past the TTL; the guidebook
        is deleted under the same holder lock (plain ``DELETE`` + cascade, no own lock).

        Returns:
            Counts of expired magic links and deleted guidebooks (logged by the entry-point, §9.6).
        """
        threshold = datetime.now(tz=UTC) - self.settings.magic_link_ttl
        expired_magic_links = 0
        deleted_guidebooks = 0

        while True:
            with self.uow.transaction():
                batch = self.leads_repo.list_expired(
                    threshold=threshold, limit=self.settings.cleanup_batch_size
                )
            if not batch:
                break
            for lead in batch:
                with self.uow.transaction():
                    fresh = self.leads_repo.get_by_id_for_update(lead.id)
                    if fresh is None or fresh.last_seen_at >= threshold:
                        continue
                    dirty = False
                    if fresh.guidebook_id is not None:
                        self.guidebooks_repo.delete(fresh.guidebook_id)
                        fresh.detach_guidebook()
                        deleted_guidebooks += 1
                        dirty = True
                    if fresh.magic_link is not None:
                        fresh.expire_magic_link()
                        expired_magic_links += 1
                        dirty = True
                    if dirty:
                        self.leads_repo.update(fresh)

        return CleanupResult(
            expired_magic_links=expired_magic_links, deleted_guidebooks=deleted_guidebooks
        )
