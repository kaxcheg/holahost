"""Protocols for persisting and reading documents and their chunks."""

from __future__ import annotations

from typing import Protocol

from domain.entities.chunk import Chunk
from domain.entities.document import Document
from domain.value_objects.document_id import DocumentId
from domain.value_objects.owner_subject import OwnerSubject


class DocumentsRepo(Protocol):
    """Persists and reads ``Document`` rows — the entity's combined read/write
    gateway (plain DDD Repository). Every method takes ``owner`` explicitly, even
    where an argument already carries it (``document.owner``): the contract is
    that every operation on both repos is owner-scoped, and an explicit parameter
    on each individual method is the one thing an adapter implementer can't miss
    while writing that method's body — a factory that binds ``owner`` once
    elsewhere (considered and rejected, see clarifications.md) would be invisible
    from inside the method actually doing the filtering."""

    def add(self, document: Document, owner: OwnerSubject) -> None:
        """Insert a new document row.

        ``owner`` must equal ``document.owner`` — passed explicitly anyway, for the
        same uniform-contract reason as every other method here, and so the adapter
        has a param to assert against as a cheap sanity check.

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: a concurrent write conflicted with this write.
            IntegrityError: a stored invariant was violated (internal defect).
        """
        ...

    def get(
        self, document_id: DocumentId, owner: OwnerSubject, *, lock: bool = False
    ) -> Document | None:
        """Read a document by id, scoped to its owner.

        A document owned by a different subject is returned as ``None``, identically
        to a document that does not exist at all (US-R06, A-13).

        Concurrency: ``lock=True`` → ``SELECT ... FOR UPDATE``, held until the
        enclosing ``UnitOfWork`` commits or rolls back.

        Args:
            document_id: The document to read.
            owner: The caller's subject; only a matching owner is ever returned.
            lock: If ``True``, issue ``SELECT ... FOR UPDATE`` and hold the row lock
                until the enclosing ``UnitOfWork`` commits or rolls back.

        Returns:
            The document, or ``None`` if it does not exist or belongs to another owner.

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: a concurrent write conflicted with this read.
            IntegrityError: a stored invariant was violated (internal defect).
        """
        ...

    def update(self, document: Document, owner: OwnerSubject) -> None:
        """Persist changes to an existing document row.

        Scope the ``WHERE`` clause by ``owner`` (the explicit param, not
        ``document.owner`` — same value, but the explicit param is what every other
        method's ``WHERE`` uses too), not just ``document.id`` — if a bug ever got
        here with a mismatched owner, the update should affect zero rows rather
        than silently writing someone else's document (US-R06, A-13).

        Concurrency: call inside the transaction opened by ``get(..., lock=True)``.

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: a concurrent write conflicted with this write.
            IntegrityError: a stored invariant was violated (internal defect).
        """
        ...

    def delete(self, document_id: DocumentId, owner: OwnerSubject) -> None:
        """Delete a document row (and, via cascade, its chunks).

        Concurrency: call inside the transaction opened by ``get(..., lock=True)``.

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: a concurrent write conflicted with this write.
            IntegrityError: a stored invariant was violated (internal defect).
        """
        ...


class ChunksRepo(Protocol):
    """Persists and removes ``Chunk`` rows — the write side of the Chunk entity
    (``VectorSearch`` is its read side)."""

    def add_many(self, chunks: list[Chunk], owner: OwnerSubject) -> None:
        """Insert new chunk rows.

        ``owner`` is defense in depth, not part of the write itself (``Chunk`` has
        no owner field): scope the insert to chunks whose ``document_id`` actually
        belongs to ``owner`` (e.g. a ``WHERE document_id IN (SELECT id FROM
        documents WHERE owner = ...)`` guard), so a bug that skipped the use case's
        own ownership check can't silently attach chunks to someone else's document
        (US-R06, A-13).

        Concurrency: for replace, call inside the transaction opened by
        ``DocumentsRepo.get(..., lock=True)``; not needed for create.

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: a concurrent write conflicted with this write.
            IntegrityError: a stored invariant was violated (internal defect).
        """
        ...

    def delete_by_document(self, document_id: DocumentId, owner: OwnerSubject) -> None:
        """Delete every chunk row belonging to ``document_id``.

        ``owner`` is defense in depth: scope the delete so it only ever removes
        chunks of a document actually owned by ``owner``, so a bug that skipped the
        use case's own ownership check can't silently destroy another owner's data
        (US-R06, A-13) — a delete is the one mistake here that isn't recoverable.

        Concurrency: call inside the transaction opened by
        ``DocumentsRepo.get(..., lock=True)``.

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: a concurrent write conflicted with this write.
            IntegrityError: a stored invariant was violated (internal defect).
        """
        ...
