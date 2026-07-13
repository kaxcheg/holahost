from infrastructure.sample.preload import SAMPLE_GUIDEBOOK_ID, load_sample_chunks
from tests._support.fakes import FakeEmbeddingModel, FakeFileParser, FakeTextChunker


class _FakeSource:
    def read(self) -> bytes:
        return b"raw sample guidebook bytes"


def test_load_sample_chunks_builds_chunks() -> None:
    chunks = load_sample_chunks(
        _FakeSource(),
        FakeFileParser(text="full sample guidebook text"),
        FakeTextChunker(chunks=["alpha", "beta"], pages=[None, None]),
        FakeEmbeddingModel(),
    )
    assert len(chunks) == 2
    assert all(c.guidebook_id == SAMPLE_GUIDEBOOK_ID for c in chunks)
    assert [c.ordinal for c in chunks] == [0, 1]
    assert [c.text for c in chunks] == ["alpha", "beta"]
    assert all(c.embedding is not None for c in chunks)


def test_sample_guidebook_id_is_stable() -> None:
    # Fixed sentinel so preloaded chunks have a recognizable, drift-free id (retrieval ignores it).
    assert str(SAMPLE_GUIDEBOOK_ID) == "00000000-0000-0000-0000-000000000001"
