"""Port for persisting and reading documents, together with their owned chunks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from application.ports.uow import UnitOfWork
from domain.entities.document import Document
from domain.value_objects.document_id import DocumentId
from domain.value_objects.owner_subject import OwnerSubject


class DocumentsRepo(ABC):
    """Persists and reads ``Document`` rows, together with the ``Chunk`` rows they
    own — one repo for the aggregate (``Document`` is the root, ``Chunk`` has no
    repo of its own, spec §4.3): a chunk is written/replaced only as part of writing
    its document, never independently.

    ``owner`` is bound at construction, not passed per call: every concrete method
    here is *final* in shape — it calls ``_bind_owner()`` before delegating to the
    matching ``_*_impl`` hook, so a subclass has no way to reach storage without the
    owner-scoping step running first (§8.0). ``_bind_owner()`` re-runs on every call
    (not just once) because it scopes the *active transaction*, and a single repo
    instance may be used across more than one transaction within a use case.
    """

    def __init__(self, uow: UnitOfWork, owner: OwnerSubject) -> None:
        self._uow = uow
        self._owner = owner

    @abstractmethod
    def _bind_owner(self) -> None:
        """Scope the active transaction to the owner this repo was constructed with,
        by whatever mechanism the adapter's storage enforces access control with
        (e.g. Postgres RLS via ``SET LOCAL``)."""
        ...

    def add(self, document: Document) -> None:
        """Insert a new document row together with its chunks (``document.chunks``,
        never ``None`` — ``Document.create`` always sets it).

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: a concurrent write conflicted with this write.
            IntegrityError: a stored invariant was violated (internal defect).
        """
        self._bind_owner()
        self._add_impl(document)

    @abstractmethod
    def _add_impl(self, document: Document) -> None: ...

    def get(self, document_id: DocumentId, *, lock: bool = False) -> Document | None:
        """Read a document by id, scoped to the owner this repo was constructed with.

        A document owned by a different subject is returned as ``None``, identically
        to a document that does not exist at all (US-R06, A-13). The returned
        document's ``chunks`` is always ``None`` — no current use case needs chunk
        contents back from a plain read, only ``chunk_count``.

        Concurrency: ``lock=True`` → ``SELECT ... FOR UPDATE``, held until the
        enclosing ``UnitOfWork`` commits or rolls back.

        Args:
            document_id: The document to read.
            lock: If ``True``, issue ``SELECT ... FOR UPDATE`` and hold the row lock
                until the enclosing ``UnitOfWork`` commits or rolls back.

        Returns:
            The document, or ``None`` if it does not exist or belongs to another owner.

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: a concurrent write conflicted with this read.
            IntegrityError: a stored invariant was violated (internal defect).
        """
        self._bind_owner()
        return self._get_impl(document_id, lock=lock)

    @abstractmethod
    def _get_impl(self, document_id: DocumentId, *, lock: bool) -> Document | None: ...

    def update(self, document: Document) -> None:
        """Persist changes to an existing document row.

        If ``document.chunks`` is ``None`` (a rename-only change — ``Document.rename``
        never touches ``chunks``), the chunk rows are left untouched. If it is a
        list (``Document.replace_content`` was called), the document's chunk rows are
        replaced wholesale with it.

        Concurrency: call inside the transaction opened by ``get(..., lock=True)``.

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: a concurrent write conflicted with this write.
            IntegrityError: a stored invariant was violated (internal defect).
            NotFoundError: the document does not exist, or belongs to another owner —
                only reachable as a caller defect (the established call pattern
                always locks-and-rechecks via ``get(..., lock=True)`` first).
        """
        self._bind_owner()
        self._update_impl(document)

    @abstractmethod
    def _update_impl(self, document: Document) -> None: ...

    def delete(self, document_id: DocumentId) -> None:
        """Delete a document row and its chunks.

        Concurrency: call inside the transaction opened by ``get(..., lock=True)``.

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: a concurrent write conflicted with this write.
            IntegrityError: a stored invariant was violated (internal defect).
            NotFoundError: the document does not exist, or belongs to another owner —
                only reachable as a caller defect (same reasoning as ``update``).
        """
        self._bind_owner()
        self._delete_impl(document_id)

    @abstractmethod
    def _delete_impl(self, document_id: DocumentId) -> None: ...


DocumentsRepoFactory = Callable[[OwnerSubject], DocumentsRepo]
"""Builds an owner-bound ``DocumentsRepo`` — the sole way a use case obtains one
(constructor injection would fix the owner before it is known, at composition time)."""
