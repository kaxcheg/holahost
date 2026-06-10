from __future__ import annotations

from dataclasses import dataclass

from domain.value_objects.chunk_id import ChunkId
from domain.value_objects.embedding import Embedding
from domain.value_objects.guidebook_id import GuidebookId


@dataclass(eq=False)
class Chunk:
    """Persistent chunk entity (spec §7.4).

    Represents one sliding-window slice of an ingested guidebook text,
    together with its pre-computed embedding. Identified by its
    system-generated ``id``; equality and hashing are by ``id``
    (spec §7.0 — persistent-entity identity): ``eq=False`` disables
    dataclass field-wise equality so the explicit ``__eq__``/``__hash__``
    govern.

    Args:
        id: System-generated identifier.
        guidebook_id: FK to the parent guidebook.
        ordinal: Zero-based index of this chunk within the source text
            (``enumerate(chunks_text)`` in the ingestion use case, §9.4).
        text: Raw text slice (600-token window, §2.5).
        embedding: L2-normalised 384-dim float32 vector (§2.5).
    """

    id: ChunkId
    guidebook_id: GuidebookId
    ordinal: int
    text: str
    embedding: Embedding

    @classmethod
    def create(
        cls,
        guidebook_id: GuidebookId,
        ordinal: int,
        text: str,
        embedding: Embedding,
    ) -> Chunk:
        """Create a new chunk with a fresh id.

        Args:
            guidebook_id: Id of the parent guidebook.
            ordinal: Zero-based position in the source text.
            text: Raw text slice.
            embedding: Pre-computed L2-normalised embedding.

        Returns:
            A new ``Chunk`` with a generated ``id``.
        """
        return cls(
            id=ChunkId.new(),
            guidebook_id=guidebook_id,
            ordinal=ordinal,
            text=text,
            embedding=embedding,
        )

    @classmethod
    def from_repo(
        cls,
        id: ChunkId,
        guidebook_id: GuidebookId,
        ordinal: int,
        text: str,
        embedding: Embedding,
    ) -> Chunk:
        """Reconstruct a chunk from persisted values (no id generation).

        Args:
            id: Persisted identifier.
            guidebook_id: Persisted parent guidebook id.
            ordinal: Persisted position index.
            text: Persisted text slice.
            embedding: Persisted embedding vector.

        Returns:
            The reconstructed ``Chunk``.
        """
        return cls(
            id=id,
            guidebook_id=guidebook_id,
            ordinal=ordinal,
            text=text,
            embedding=embedding,
        )

    def __eq__(self, other: object) -> bool:
        """Equality by ``id`` (persistent-entity identity, spec §7.0)."""
        if not isinstance(other, Chunk):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash by ``id`` (stable under mutation)."""
        return hash(self.id)
