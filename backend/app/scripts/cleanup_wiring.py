"""DI wiring for the cleanup Lambda (spec §8.6 / §4.7) — the testable assembly.

``build_cleanup()`` assembles the mini-container for the EventBridge-triggered cleanup Lambda;
``run()`` executes both cleanup use cases and logs the combined totals. ``bootstrap_cleanup.py`` runs
them on cold start. Kept separate (no import-time side effects) so unit tests import ``run`` without
building the real graph.
"""

from __future__ import annotations

from dataclasses import dataclass

from application.ports.rate import RateLimiter
from application.ports.repos import GuidebooksRepo, LeadsRepo
from application.ports.uow import UnitOfWork
from application.use_cases.cleanup_expired import CleanupExpiredUseCase
from application.use_cases.cleanup_rate_counters import CleanupRateCountersUseCase
from config.config import Settings
from config.logging import log_event
from infrastructure.db.sqlalchemy.postgres_guidebooks_repo import PostgresGuidebooksRepo
from infrastructure.db.sqlalchemy.postgres_leads_repo import PostgresLeadsRepo
from infrastructure.db.sqlalchemy.postgres_rate_limiter import PostgresRateLimiter
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork


@dataclass
class CleanupContainer:
    """Cold-start dependency graph for the cleanup Lambda (spec §8.6)."""

    settings: Settings
    uow: UnitOfWork
    leads_repo: LeadsRepo
    guidebooks_repo: GuidebooksRepo
    rate: RateLimiter
    cleanup_expired: CleanupExpiredUseCase
    cleanup_rate_counters: CleanupRateCountersUseCase


def build_cleanup() -> CleanupContainer:
    """Construct the cleanup Lambda dependency graph (spec §8.6). Runs once per cold start."""
    settings = Settings.from_env()
    uow = PostgresUnitOfWork(settings.database_url)
    leads_repo = PostgresLeadsRepo(uow)
    guidebooks_repo = PostgresGuidebooksRepo(uow)
    rate = PostgresRateLimiter(uow, settings)
    return CleanupContainer(
        settings=settings,
        uow=uow,
        leads_repo=leads_repo,
        guidebooks_repo=guidebooks_repo,
        rate=rate,
        cleanup_expired=CleanupExpiredUseCase(leads_repo, guidebooks_repo, uow, settings),
        cleanup_rate_counters=CleanupRateCountersUseCase(rate, uow, settings),
    )


def run(container: CleanupContainer) -> dict[str, int]:
    """Run both cleanup use cases and log the combined totals (§4.7)."""
    expired = container.cleanup_expired.execute()
    counters = container.cleanup_rate_counters.execute()
    log_event(
        "cleanup_completed",
        expired_magic_links=expired.expired_magic_links,
        deleted_guidebooks=expired.deleted_guidebooks,
        deleted_rate_windows=counters.deleted_windows,
    )
    return {
        "expired_magic_links": expired.expired_magic_links,
        "deleted_guidebooks": expired.deleted_guidebooks,
        "deleted_rate_windows": counters.deleted_windows,
    }
