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
    """Port: persistence for ``Guidebook`` (spec §8.2.5).

    A guidebook is a **child** of its ``Lead`` holder (reachable only via ``lead.guidebook_id``):
    every WRITE path first locks the lead (``LeadsRepo.*_for_update``), so these methods take NO
    lock of their own — the holder lock serializes all concurrent writes (§9.0). The unlocked READ
    on GenerateResponse's gather transaction (``get`` here, ``list_for_guidebook`` on ``ChunksRepo``)
    cannot hold a lock across the LLM call, but is NOT served stale: GenerateResponse re-validates
    ``lead.guidebook_id`` under the holder lock after the LLM and rejects a concurrent replace/delete (§9.5).
    """

    def get(self, guidebook_id: GuidebookId) -> Guidebook | None:
        """Return the guidebook by id, or None — takes no lock of its own.

        On holder-locked paths (resolve, generate's post-LLM re-read) it runs under the already-held
        lead lock. On GenerateResponse's FIRST transaction it runs WITHOUT a lock (none may span the
        following LLM call); a concurrent replace/delete is NOT served stale — generate re-validates
        ``lead.guidebook_id`` under the holder lock after the LLM and rejects the mismatch (§9.5 / §9.0).
        """
        ...

    def add(self, guidebook: Guidebook) -> None:
        """Insert a new guidebook (under the held lead lock)."""
        ...

    def delete(self, guidebook_id: GuidebookId) -> None:
        """Delete a guidebook by id (CASCADE chunks, §4.3).

        Plain ``DELETE`` + cascade in the caller's transaction, NO own lock: the row is reachable
        only through the already-locked lead holder, and on replace the lead is repointed to the new
        guidebook BEFORE the old is deleted (add → repoint → delete, §9.4), so no live path reaches
        the row being deleted (§9.0).
        """
        ...

    def update(self, guidebook: Guidebook) -> None:
        """Persist the guidebook's state (e.g. bumped last_accessed_at; under the held lead lock).
        NO own lock: the row is reachable only through the already-locked lead holder"""
        ...


class ChunksRepo(Protocol):
    """Port: persistence for ``Chunk`` (spec §8.2.5).

    A chunk is a **child of a Guidebook** (grandchild of the ``Lead`` holder): the write path
    (``bulk_add``) first locks the lead (``LeadsRepo.*_for_update``), so these methods take NO lock
    of their own — the holder lock serializes concurrent access (§9.0). Chunks are never deleted
    directly: they are removed by ``ON DELETE CASCADE`` when their guidebook is deleted (§4.3 / §9.4).
    """

    def list_for_guidebook(self, guidebook_id: GuidebookId) -> list[Chunk]:
        """Return all chunks for a guidebook — takes no lock.

        Used only by GenerateResponse's FIRST (unlocked) transaction to gather retrieval context.
        The unlocked read is safe — NOT an accepted stale-read: chunks are immutable for a given
        guidebook id (a replace creates a NEW guidebook id, never mutates an existing one's chunks),
        and GenerateResponse re-validates ``lead.guidebook_id`` under the holder lock after the LLM
        call — a concurrent replace/delete is rejected there (``NoGuidebookAttachedError``), never
        served stale (§9.5 / §9.0).
        """
        ...

    def bulk_add(self, chunks: list[Chunk]) -> None:
        """Insert many chunks in one operation — under the held lead lock, no lock of its own.

        Inserted together with the new guidebook while the upload holds the lead holder lock (§9.4).
        """
        ...


class LeadsRepo(Protocol):
    """Port: persistence for ``Lead`` (spec §8.2.5).

    ``Lead`` is the aggregate **holder**: a guidebook (and its chunks) is reachable only via
    ``lead.guidebook_id``. So any use case running a read → decide → write on a lead (or its
    guidebook) must take the lead's row lock FIRST and hold it to commit — that single holder lock
    serializes every concurrent writer of the aggregate, and the child guidebook/chunk operations
    need no lock of their own (§9.0).

    Lock discipline (adapter requirement): the ``*_for_update`` reads issue ``SELECT ... FOR
    UPDATE`` as the first statement of the write transaction and hold the lock to commit; the plain
    reads do NOT lock — they are for read-only paths, or pre-reads before long non-DB work (parse /
    LLM) where a lock must not be held. A read → decide → write path must use a ``*_for_update``.

    Capture upsert (§9.2): ``email`` is unique; the new-email insert race (two callers both read
    None → both insert) is stopped by the unique constraint on ``email`` (``INSERT ... ON CONFLICT``
    / catch the violation), since there is no row to lock yet.
    """

    def get_by_id_for_update(self, id: LeadId) -> Lead | None:
        """Return the lead by id under a row lock (``SELECT ... FOR UPDATE``), or None.

        Race-protection (adapter requirement): ``CleanupExpiredUseCase`` issues this as the first
        statement of the per-lead transaction; the lock is held to commit so a concurrent
        ``/resolve`` / ``/generate`` ``touch`` (or another writer) cannot interleave between this
        read and the subsequent ``update`` / guidebook ``delete`` (§9.6 / §9.0).
        """
        ...

    def get_by_email_for_update(self, email: Email) -> Lead | None:
        """Return the lead by email under a row lock (``SELECT ... FOR UPDATE``), or None.

        Race-protection (adapter requirement): ``CaptureLeadUseCase`` issues this first on the
        existing-email path; the lock serializes the read-modify-write so a concurrent cleanup /
        capture cannot make the blind ``update`` resurrect a stale ``guidebook_id`` over a DB
        ``ON DELETE SET NULL`` (§9.2 / §9.0). New-email inserts (None returned) rely on the unique
        ``email`` constraint, not this lock.
        """
        ...

    def get_by_magic_link(self, magic_link: MagicLink) -> Lead | None:
        """Return the lead by magic link, or None — NO lock (read-only / pre-read).

        For paths that only read, or pre-read before long non-DB work — the upload resolve-check
        and the generate retrieval gather, where a row lock must not span parsing / the LLM call. A
        read → decide → write path must use :meth:`get_by_magic_link_for_update` instead.
        """
        ...

    def get_by_magic_link_for_update(self, magic_link: MagicLink) -> Lead | None:
        """Return the lead by magic link under a row lock (``SELECT ... FOR UPDATE``), or None.

        Race-protection (adapter requirement): the holder-lock read for the write transactions of
        ``ResolveMagicLinkUseCase`` / ``UploadGuidebookUseCase`` / ``GenerateResponseUseCase`` —
        first statement, held to commit, so the lead's read-modify-write (touch / attach / replace)
        and any child-guidebook write serialize against concurrent writers (§9.0).
        """
        ...

    def add(self, lead: Lead) -> None:
        """Insert a new lead (capture, new email). Concurrency: unique ``email`` constraint."""
        ...

    def update(self, lead: Lead) -> None:
        """Idempotent UPDATE: persist the lead's full current state by ``lead.id``.

        Blind full-row write — safe only because the transaction holds the lead's row lock from a
        ``*_for_update`` read (§9.0); without it a concurrent writer would be lost or resurrected.
        """
        ...

    def list_expired(self, threshold: datetime, limit: int) -> list[Lead]:
        """Return up to ``limit`` leads with a non-null magic_link and ``last_seen_at < threshold``.

        Cleanup candidate list (§9.6) — NO lock: a cheap work-list read in its own short
        transaction. The authoritative per-lead lock is taken later by
        :meth:`get_by_id_for_update`; this read intentionally holds no locks across the batch.
        """
        ...


class SampleBudgetRepo(Protocol):
    """Port: persistence for the daily sample budget (spec §8.2.5).

    The daily budget row is its own aggregate holder. ``get_or_create`` (no lock) is for the
    read-only pre-check; the post-usage read-modify-write must use
    :meth:`get_or_create_for_update` so concurrent usage updates serialize and are not lost (§9.1).
    Both must be safe under a concurrent first-create for the same ``day`` (unique on ``day`` +
    idempotent upsert — no duplicate rows, no error). The ONLY accepted race is the *pre-check*
    overshoot — up to N concurrent calls passing ``is_exhausted`` before their usage lands, bounded
    by N * MAX_OUTPUT_TOKENS (§9.1 / §10.2); the usage accounting itself must not lose updates, or
    that bound would not hold.
    """

    def get_or_create(self, day: date) -> SampleBudgetState:
        """Return the budget row for ``day``, creating a zeroed row if absent — NO lock.

        For the read-only pre-check only; the bounded pre-check overshoot is accepted (§10.2).
        """
        ...

    def get_or_create_for_update(self, day: date) -> SampleBudgetState:
        """Return the budget row for ``day`` (creating it if absent) under a row lock.

        Race-protection (adapter requirement): ``SELECT ... FOR UPDATE`` as the first statement of
        the post-usage transaction, held to commit, so the ``add_usage`` → ``save``
        read-modify-write serializes against concurrent samples and no recorded usage is lost
        (§9.1 / §9.0).
        """
        ...

    def save(self, state: SampleBudgetState) -> None:
        """Persist the budget state (under the held lock from :meth:`get_or_create_for_update`)."""
        ...
