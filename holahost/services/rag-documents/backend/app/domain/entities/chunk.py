"""The `Chunk` entity."""

from __future__ import annotations

from dataclasses import dataclass

from domain.value_objects.chunk_id import ChunkId
from domain.value_objects.chunk_index import ChunkIndex
from domain.value_objects.document_id import DocumentId
from domain.value_objects.embedding import Embedding
from domain.value_objects.page_number import PageNumber


@dataclass(frozen=True, eq=False)
class Chunk:
    """An indexed text fragment of a document (spec §4.3).

    Immutable (`frozen=True`) — spec §4.3 states this outright:
    a chunk is born and dies only with its document, no update operation
    exists. `eq=False` disables the dataclass's field-wise default equality
    so the hand-written `__eq__`/`__hash__` below (identity by `id`) govern
    instead — the two are independent dataclass options and compose freely.

    Not checked here (needs an infrastructure dependency this layer must not
    import, or a whole-collection view this type doesn't have): token-length
    vs. `CHUNK_WINDOW_TOKENS` (needs the embedding model's tokenizer — the
    chunker's job, R-16, which only ever produces in-window chunks by
    construction); page-boundary-crossing and embedding-matches-text
    (process-correctness guarantees from whoever calls `create`, not
    independently re-derivable here).

    :param id: Self-generated identifier.
    :param document_id: The owning document.
    :param index: Position within the document.
    :param text: Non-empty after `strip`.
    :param embedding: This fragment's vector.
    :param page: Source page, or `PageNumber(None)` for pageless formats.
    """

    id: ChunkId
    document_id: DocumentId
    index: ChunkIndex
    text: str
    embedding: Embedding
    page: PageNumber

    def __post_init__(self) -> None:
        # Parser/chunker output, not client input directly — internal defect
        # if empty, so plain ValueError.
        if not self.text.strip():
            raise ValueError("Chunk text must not be empty")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Chunk):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def create(
        cls,
        document_id: DocumentId,
        index: ChunkIndex,
        text: str,
        embedding: Embedding,
        page: PageNumber,
    ) -> Chunk:
        """Create a new chunk with a fresh id.

        :raises ValueError: `text` is empty after `strip`.
        """
        return cls(
            id=ChunkId.new(),
            document_id=document_id,
            index=index,
            text=text,
            embedding=embedding,
            page=page,
        )

    @classmethod
    def from_repo(
        cls,
        id: ChunkId,
        document_id: DocumentId,
        index: ChunkIndex,
        text: str,
        embedding: Embedding,
        page: PageNumber,
    ) -> Chunk:
        """Reconstruct a chunk from storage — no regeneration, no re-validation beyond `text`."""
        return cls(
            id=id,
            document_id=document_id,
            index=index,
            text=text,
            embedding=embedding,
            page=page,
        )
