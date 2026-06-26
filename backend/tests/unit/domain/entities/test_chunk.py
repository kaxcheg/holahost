import numpy as np

from domain.entities.chunk import Chunk
from domain.value_objects.chunk_id import ChunkId
from domain.value_objects.embedding import Embedding
from domain.value_objects.guidebook_id import GuidebookId

_GID = GuidebookId.new()
_GID2 = GuidebookId.new()
_VEC = np.zeros(384, dtype=np.float32)
_VEC[0] = 1.0  # unit vector → L2-norm == 1
_EMB = Embedding(vector=_VEC)
_TEXT = "Check-in is at 3pm."


class TestChunk:
    def test_create_sets_fields(self) -> None:
        chunk = Chunk.create(
            guidebook_id=_GID, ordinal=0, text=_TEXT, page=None, embedding=_EMB
        )
        assert isinstance(chunk.id, ChunkId)
        assert chunk.guidebook_id == _GID
        assert chunk.ordinal == 0
        assert chunk.text == _TEXT
        assert chunk.embedding == _EMB

    def test_create_generates_unique_ids(self) -> None:
        ids = {
            Chunk.create(
                guidebook_id=_GID, ordinal=i, text=_TEXT, page=None, embedding=_EMB
            ).id
            for i in range(100)
        }
        assert len(ids) == 100

    def test_create_carries_page_provenance(self) -> None:
        chunk = Chunk.create(
            guidebook_id=_GID, ordinal=0, text=_TEXT, page=3, embedding=_EMB
        )
        assert chunk.page == 3

    def test_from_repo_page_can_be_none(self) -> None:
        chunk = Chunk.from_repo(
            id=ChunkId.new(),
            guidebook_id=_GID,
            ordinal=0,
            text=_TEXT,
            page=None,
            embedding=_EMB,
        )
        assert chunk.page is None

    def test_from_repo_reconstructs_verbatim(self) -> None:
        cid = ChunkId.new()
        chunk = Chunk.from_repo(
            id=cid,
            guidebook_id=_GID,
            ordinal=3,
            text="Checkout by 11am.",
            page=None,
            embedding=_EMB,
        )
        assert chunk.id == cid
        assert chunk.guidebook_id == _GID
        assert chunk.ordinal == 3
        assert chunk.text == "Checkout by 11am."
        assert chunk.embedding == _EMB

    def test_equal_when_same_id_regardless_of_other_fields(self) -> None:
        cid = ChunkId.new()
        vec2 = np.zeros(384, dtype=np.float32)
        vec2[1] = 1.0
        emb2 = Embedding(vector=vec2)
        a = Chunk.from_repo(
            id=cid, guidebook_id=_GID, ordinal=0, text="A", page=None, embedding=_EMB
        )
        b = Chunk.from_repo(
            id=cid, guidebook_id=_GID2, ordinal=99, text="B", page=None, embedding=emb2
        )
        assert a == b

    def test_not_equal_when_different_id_or_other_type(self) -> None:
        a = Chunk.create(
            guidebook_id=_GID, ordinal=0, text=_TEXT, page=None, embedding=_EMB
        )
        b = Chunk.create(
            guidebook_id=_GID, ordinal=0, text=_TEXT, page=None, embedding=_EMB
        )
        assert a != b
        not_a_chunk: object = "not-a-chunk"
        assert a != not_a_chunk

    def test_hashable_by_id(self) -> None:
        cid = ChunkId.new()
        vec2 = np.zeros(384, dtype=np.float32)
        vec2[1] = 1.0
        emb2 = Embedding(vector=vec2)
        a = Chunk.from_repo(
            id=cid, guidebook_id=_GID, ordinal=0, text="A", page=None, embedding=_EMB
        )
        b = Chunk.from_repo(
            id=cid, guidebook_id=_GID2, ordinal=99, text="B", page=None, embedding=emb2
        )
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
