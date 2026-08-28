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

MAX_CHUNKS_PER_DOCUMENT = 500  # spec §3.7


@dataclass(eq=False)
class Document:
    """An indexed document (spec §4.2) — the aggregate root for its `Chunk`s: a chunk
    is never created, replaced, or removed except through `create`/`replace_content`
    here, which is where "chunks belong to this document" and "at least one chunk"
    are enforced (§4.3 — Chunk itself has no repo, no update, and dies with its
    document).

    Mutable — `name` changes on rename, `mime_type`/`chunk_count` change on
    content replacement, `updated_at` changes with either. `owner` is fixed
    at creation (ownership transfer is out of scope, spec §4.2). Equality
    and hashing are by `id` (entity identity), not field values —
    `eq=False` disables the dataclass's field-wise default so the
    hand-written `__eq__`/`__hash__` below govern instead.

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

        `id` is caller-provided, not self-generated: chunks need a `document_id` to
        exist, so the caller must generate the id (`DocumentId.new()`) and build
        `chunks` with it before calling this — the same order `create_document`/
        `replace_document` already use for the id-then-chunks dependency.

        :raises ChunkCountExceededError: more than `MAX_CHUNKS_PER_DOCUMENT` chunks.
            Only knowable after chunking completes, and the one client-facing invariant
            here (US-R01: 422 `TooManyChunksError`) — which is why it has a type of its
            own: a caller translating it must select it, not catch the base.
        :raises DomainValidationError: with `field` unset — `chunks` is empty, or
            contains a chunk whose `document_id` does not match `id`. Structurally
            unreachable (empty documents are rejected earlier, at the parsing stage,
            US-R01; a mismatched `document_id` would be a caller defect), and so an
            internal defect if it does happen: nothing translates it, it surfaces as
            `500`.
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
        set — and bump `updated_at` (US-R02).

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
