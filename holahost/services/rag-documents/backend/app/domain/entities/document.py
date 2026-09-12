"""The `Document` entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from domain.entities.chunk import Chunk
from domain.exceptions import ChunkCountExceededError, DomainValidationError
from domain.value_objects.document_id import DocumentId
from domain.value_objects.document_name import DocumentName
from domain.value_objects.mime_type import MimeType
from domain.value_objects.owner_subject import OwnerSubject

MAX_CHUNKS_PER_DOCUMENT = 500


@dataclass(eq=False)
class Document:
    """An indexed document — the aggregate root for its `Chunk`s: a chunk is never
    created, replaced, or removed except through `create`/`replace_content` here,
    which is where "chunks belong to this document" and "at least one chunk" are
    enforced. `Chunk` itself has no repository, no update, and dies with its document.

    Mutable — `name` changes on rename, `mime_type`/`chunk_count` on content
    replacement, `updated_at` with either. `owner` is fixed at creation; transferring
    ownership is out of scope. Equality and hashing are by `id`, which is what
    `eq=False` plus the hand-written `__eq__`/`__hash__` below achieve.

    :param id: Self-generated identifier.
    :param owner: Immutable after creation.
    :param name: The only field a rename touches directly.
    :param mime_type: The source file's format.
    :param chunk_count: 1..MAX_CHUNKS_PER_DOCUMENT — persisted independently of
        `chunks` so it is available without loading them (`from_repo` never does).
    :param created_at: UTC, aware, set once at creation.
    :param updated_at: UTC, aware; >= created_at.
    :param chunks: The document's current chunks, or `None` when not loaded — only
        `create`/`replace_content` ever populate this; `from_repo` never does (no use
        case needs chunk contents back from a plain read, only `chunk_count`).
    """

    id: DocumentId
    owner: OwnerSubject
    name: DocumentName
    mime_type: MimeType
    chunk_count: int
    created_at: datetime
    updated_at: datetime
    chunks: list[Chunk] | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Document):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def create(
        cls,
        id: DocumentId,
        owner: OwnerSubject,
        name: DocumentName,
        mime_type: MimeType,
        chunks: list[Chunk],
    ) -> Document:
        """Create a new document with matching timestamps.

        `id` is caller-provided: chunks need a `document_id` to exist, so the caller
        generates the id and builds `chunks` with it before calling this.

        :raises ChunkCountExceededError: more than `MAX_CHUNKS_PER_DOCUMENT` chunks —
            the one client-facing invariant here (422 `TooManyChunksError`), which is
            why it has a type of its own for the caller to select.
        :raises DomainValidationError: with `field` unset — `chunks` is empty, or holds a
            chunk belonging to another document. Both are structurally unreachable, so
            either is an internal defect: nothing translates it, and it surfaces as 500.
        """
        _validate_chunks(id, chunks)
        now = datetime.now(tz=UTC)
        return cls(
            id=id,
            owner=owner,
            name=name,
            mime_type=mime_type,
            chunk_count=len(chunks),
            created_at=now,
            updated_at=now,
            chunks=chunks,
        )

    @classmethod
    def from_repo(
        cls,
        id: DocumentId,
        owner: OwnerSubject,
        name: DocumentName,
        mime_type: MimeType,
        chunk_count: int,
        created_at: datetime,
        updated_at: datetime,
    ) -> Document:
        """Reconstruct a document from storage — no regeneration, no re-validation.
        `chunks` is left `None`: a plain read never needs chunk contents back."""
        return cls(
            id=id,
            owner=owner,
            name=name,
            mime_type=mime_type,
            chunk_count=chunk_count,
            created_at=created_at,
            updated_at=updated_at,
        )

    def rename(self, name: DocumentName) -> None:
        """Change the document's display name and bump `updated_at`. Does not
        touch chunks."""
        self.name = name
        self.updated_at = datetime.now(tz=UTC)

    def replace_content(self, mime_type: MimeType, chunks: list[Chunk]) -> None:
        """Replace the document's content — new mime type and the full new chunk
        set — and bump `updated_at`.

        :raises ChunkCountExceededError: see `create`.
        :raises DomainValidationError: see `create` — the two unset-`field` ones.
        """
        _validate_chunks(self.id, chunks)
        self.mime_type = mime_type
        self.chunk_count = len(chunks)
        self.chunks = chunks
        self.updated_at = datetime.now(tz=UTC)


def _validate_chunks(document_id: DocumentId, chunks: list[Chunk]) -> None:
    if not chunks:
        raise DomainValidationError("Document must have at least one chunk")
    if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
        raise ChunkCountExceededError(MAX_CHUNKS_PER_DOCUMENT)
    if any(chunk.document_id != document_id for chunk in chunks):
        raise DomainValidationError("All chunks must belong to this document")
