"""The `Document` entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from domain.exceptions import DomainValidationError
from domain.value_objects.document_id import DocumentId
from domain.value_objects.document_name import DocumentName
from domain.value_objects.mime_type import MimeType
from domain.value_objects.owner_subject import OwnerSubject

MAX_CHUNKS_PER_DOCUMENT = 500  # spec §3.7


@dataclass(eq=False)
class Document:
    """An indexed document (spec §4.2).

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
    :param chunk_count: 1..MAX_CHUNKS_PER_DOCUMENT.
    :param created_at: UTC, aware, set once at creation.
    :param updated_at: UTC, aware; >= created_at.
    """

    id: DocumentId
    owner: OwnerSubject
    name: DocumentName
    mime_type: MimeType
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Document):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def create(
        cls, owner: OwnerSubject, name: DocumentName, mime_type: MimeType, chunk_count: int
    ) -> Document:
        """Create a new document with a fresh id and matching timestamps.

        :raises ValueError: `chunk_count < 1` — should be structurally
            unreachable (empty documents are rejected earlier, at the
            parsing stage, US-R01), so this signals an internal defect.
        :raises DomainValidationError: `chunk_count > MAX_CHUNKS_PER_DOCUMENT`
            — only knowable after chunking completes, a real client-facing
            path (US-R01: 422 ERR_TOO_MANY_CHUNKS).
        """
        _validate_chunk_count(chunk_count)
        now = datetime.now(tz=UTC)
        return cls(
            id=DocumentId.new(),
            owner=owner,
            name=name,
            mime_type=mime_type,
            chunk_count=chunk_count,
            created_at=now,
            updated_at=now,
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
        """Reconstruct a document from storage — no regeneration, no re-validation."""
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
        """Change the document's display name and bump `updated_at`."""
        self.name = name
        self.updated_at = datetime.now(tz=UTC)

    def replace_content(self, mime_type: MimeType, chunk_count: int) -> None:
        """Update fields that change when content is replaced (US-R02) and bump `updated_at`.

        :raises ValueError: see `create`.
        :raises DomainValidationError: see `create`.
        """
        _validate_chunk_count(chunk_count)
        self.mime_type = mime_type
        self.chunk_count = chunk_count
        self.updated_at = datetime.now(tz=UTC)


def _validate_chunk_count(chunk_count: int) -> None:
    if chunk_count < 1:
        raise ValueError("Document chunk_count must be at least 1")
    if chunk_count > MAX_CHUNKS_PER_DOCUMENT:
        raise DomainValidationError(
            f"Document chunk_count exceeds {MAX_CHUNKS_PER_DOCUMENT}", field="chunk_count"
        )
