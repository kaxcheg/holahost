import dataclasses

import pytest

from domain.entities.chunk import Chunk
from domain.value_objects.chunk_id import ChunkId
from domain.value_objects.chunk_index import ChunkIndex
from domain.value_objects.document_id import DocumentId
from domain.value_objects.embedding import EMBEDDING_DIM, Embedding
from domain.value_objects.page_number import PageNumber

_DOC_ID = DocumentId.new()
_VEC = tuple(1.0 if i == 0 else 0.0 for i in range(EMBEDDING_DIM))


def _embedding() -> Embedding:
    return Embedding(_VEC)


class TestChunk:
    def test_create_sets_fields(self) -> None:
        chunk = Chunk.create(
            document_id=_DOC_ID,
            index=ChunkIndex(0),
            text="hello",
            embedding=_embedding(),
            page=PageNumber(1),
        )
        assert chunk.document_id == _DOC_ID
        assert chunk.index.value == 0
        assert chunk.text == "hello"
        assert chunk.page.value == 1

    def test_create_generates_a_unique_id(self) -> None:
        a = Chunk.create(
            document_id=_DOC_ID,
            index=ChunkIndex(0),
            text="a",
            embedding=_embedding(),
            page=PageNumber(None),
        )
        b = Chunk.create(
            document_id=_DOC_ID,
            index=ChunkIndex(1),
            text="b",
            embedding=_embedding(),
            page=PageNumber(None),
        )
        assert a.id != b.id

    def test_create_rejects_empty_text(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            Chunk.create(
                document_id=_DOC_ID,
                index=ChunkIndex(0),
                text="   ",
                embedding=_embedding(),
                page=PageNumber(None),
            )

    def test_create_rejects_a_negative_index(self) -> None:
        # ChunkIndex itself enforces >= 0 — this confirms Chunk is
        # actually wired to that VO, not silently accepting a raw int.
        with pytest.raises(ValueError, match="negative"):
            Chunk.create(
                document_id=_DOC_ID,
                index=ChunkIndex(-1),
                text="a",
                embedding=_embedding(),
                page=PageNumber(None),
            )

    def test_from_repo_reconstructs_verbatim(self) -> None:
        chunk_id = ChunkId.new()
        chunk = Chunk.from_repo(
            id=chunk_id,
            document_id=_DOC_ID,
            index=ChunkIndex(2),
            text="hello",
            embedding=_embedding(),
            page=PageNumber(None),
        )
        assert chunk.id == chunk_id
        assert chunk.page.value is None

    def test_is_immutable(self) -> None:
        chunk = Chunk.create(
            document_id=_DOC_ID,
            index=ChunkIndex(0),
            text="hello",
            embedding=_embedding(),
            page=PageNumber(None),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            chunk.text = "changed"  # type: ignore[misc]

    def test_equal_when_same_id_regardless_of_other_fields(self) -> None:
        chunk_id = ChunkId.new()
        a = Chunk.from_repo(
            id=chunk_id,
            document_id=_DOC_ID,
            index=ChunkIndex(0),
            text="a",
            embedding=_embedding(),
            page=PageNumber(None),
        )
        b = Chunk.from_repo(
            id=chunk_id,
            document_id=DocumentId.new(),
            index=ChunkIndex(9),
            text="different",
            embedding=_embedding(),
            page=PageNumber(3),
        )
        assert a == b

    def test_not_equal_when_different_id_or_other_type(self) -> None:
        a = Chunk.create(
            document_id=_DOC_ID,
            index=ChunkIndex(0),
            text="a",
            embedding=_embedding(),
            page=PageNumber(None),
        )
        b = Chunk.create(
            document_id=_DOC_ID,
            index=ChunkIndex(1),
            text="a",
            embedding=_embedding(),
            page=PageNumber(None),
        )
        assert a != b
        assert a != object()

    def test_hashable_by_id(self) -> None:
        chunk_id = ChunkId.new()
        a = Chunk.from_repo(
            id=chunk_id,
            document_id=_DOC_ID,
            index=ChunkIndex(0),
            text="a",
            embedding=_embedding(),
            page=PageNumber(None),
        )
        b = Chunk.from_repo(
            id=chunk_id,
            document_id=_DOC_ID,
            index=ChunkIndex(0),
            text="a",
            embedding=_embedding(),
            page=PageNumber(None),
        )
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
