from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from application.dto.leads import ResolveMagicLinkCmd, ResolveMagicLinkResult
from application.exceptions import InvalidMagicLinkError, magic_link_validation
from application.ports.rate import RateLimiter, RateLimitScope
from application.ports.repos import GuidebooksRepo, LeadsRepo
from application.ports.uow import UnitOfWork
from config.config import Settings
from domain.entities.lead import Lead
from domain.value_objects.magic_link import MagicLink


@dataclass
class ResolveMagicLinkUseCase:
    """Resolve a magic link to its lead + optional guidebook metadata (spec §9.3)."""

    rate: RateLimiter
    leads_repo: LeadsRepo
    guidebooks_repo: GuidebooksRepo
    uow: UnitOfWork
    settings: Settings

    def execute(self, cmd: ResolveMagicLinkCmd) -> ResolveMagicLinkResult:
        """Resolve the link, soft-expire an over-TTL guidebook to null, bump ``last_seen_at``.

        Args:
            cmd: The resolve command (magic-link token + ip hash).

        Returns:
            The lead's email/flow and the attached guidebook's metadata (or nulls).

        :raises RateLimitExceededError: per-ip or per-magic-link cap exceeded (§9.8).
        :raises InvalidMagicLinkError: token empty/invalid, unknown, or already expired (§9.8).
        """
        with self.uow.transaction():
            self.rate.check_and_increment(RateLimitScope.IP, cmd.ip_hash)
        with magic_link_validation():
            magic_link = MagicLink(cmd.magic_link)
        with self.uow.transaction():
            lead = self.leads_repo.get_by_magic_link_for_update(magic_link)
            if lead is None:
                raise InvalidMagicLinkError()
            self.rate.check_and_increment(RateLimitScope.MAGIC_LINK, str(lead.id))
            guidebook = self.guidebooks_repo.get(lead.guidebook_id) if lead.guidebook_id else None
            # Soft-expire the guidebook view if the lead has been inactive past the TTL — checked
            # BEFORE touch(), so last_seen_at still reflects the prior activity (§10.1 signal).
            if guidebook is not None and self._expired(lead):
                guidebook = None
            lead.touch()
            self.leads_repo.update(lead)
        return ResolveMagicLinkResult(
            email=lead.email.value,
            flow=lead.flow.value,
            guidebook_id=str(guidebook.id) if guidebook else None,
            guidebook_name=guidebook.name.value if guidebook else None,
            guidebook_created_at=guidebook.created_at.isoformat() if guidebook else None,
        )

    def _expired(self, lead: Lead) -> bool:
        """True if the lead has been inactive past the TTL.

        Signal is ``Lead.last_seen_at`` (§10.1), aligned with the cleanup-Lambda (§9.6) — NOT
        ``Guidebook.last_accessed_at`` (analytics-only, bumped solely on ``/api/generate``). Must be
        called before ``lead.touch()`` so the prior activity is still reflected.
        """
        return datetime.now(tz=UTC) - lead.last_seen_at > self.settings.magic_link_ttl
