from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from domain.entities.chunk import Chunk
from domain.entities.guidebook import Guidebook
from domain.entities.lead import Lead
from domain.entities.sample_budget_state import SampleBudgetState
from domain.value_objects.email import Email
from domain.value_objects.guidebook_id import GuidebookId
from domain.value_objects.lead_id import LeadId
from domain.value_objects.magic_link import MagicLink


class GuidebooksRepo(Protocol):
    """Port: persistence for ``Guidebook`` (spec §8.2.5)."""

    def get(self, guidebook_id: GuidebookId) -> Guidebook | None:
        """Return the guidebook by id, or None if absent."""
        ...

    def add(self, guidebook: Guidebook) -> None:
        """Insert a new guidebook."""
        ...

    def delete(self, guidebook_id: GuidebookId) -> None:
        """Delete a guidebook by id (CASCADE chunks, §4.3)."""
        ...

    def update(self, guidebook: Guidebook) -> None:
        """Persist the guidebook's current state (e.g. bumped last_accessed_at)."""
        ...


class ChunksRepo(Protocol):
    """Port: persistence for ``Chunk`` (spec §8.2.5)."""

    def list_for_guidebook(self, guidebook_id: GuidebookId) -> list[Chunk]:
        """Return all chunks for a guidebook."""
        ...

    def bulk_add(self, chunks: list[Chunk]) -> None:
        """Insert many chunks in one operation."""
        ...


class LeadsRepo(Protocol):
    """Port: persistence for ``Lead`` (spec §8.2.5)."""

    def get_by_id(self, id: LeadId) -> Lead | None:
        """Return the lead by id, or None."""
        ...

    def get_by_email(self, email: Email) -> Lead | None:
        """Return the lead by email, or None."""
        ...

    def get_by_magic_link(self, magic_link: MagicLink) -> Lead | None:
        """Return the lead by magic link, or None."""
        ...

    def add(self, lead: Lead) -> None:
        """Insert a new lead."""
        ...

    def update(self, lead: Lead) -> None:
        """Idempotent UPDATE: persist the lead's full current state by ``lead.id``."""
        ...

    def list_expired(self, threshold: datetime, limit: int) -> list[Lead]:
        """Return up to ``limit`` leads with a non-null magic_link and ``last_seen_at <
        threshold`` (cleanup, §9.6)."""
        ...


class SampleBudgetRepo(Protocol):
    """Port: persistence for the daily sample budget (spec §8.2.5)."""

    def get_or_create(self, day: date) -> SampleBudgetState:
        """Return the budget row for ``day``, creating a zeroed row if absent."""
        ...

    def save(self, state: SampleBudgetState) -> None:
        """Persist the budget state."""
        ...
