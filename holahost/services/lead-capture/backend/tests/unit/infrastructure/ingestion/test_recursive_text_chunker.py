from domain.value_objects.parsed_segment import ParsedSegment
from infrastructure.ingestion.recursive_text_chunker import RecursiveTextChunker


def test_chunks_stay_within_window_and_keep_page() -> None:
    chunker = RecursiveTextChunker(length_function=len, chunk_window=10, chunk_overlap=0)
    out = chunker.chunk([ParsedSegment(text="a" * 25, page=0), ParsedSegment(text="b" * 5, page=1)])
    assert all(len(s.text) <= 10 for s in out)
    assert {s.page for s in out} == {0, 1}
    assert out[-1].page == 1


def test_empty_segments_yield_empty() -> None:
    chunker = RecursiveTextChunker(length_function=len, chunk_window=10, chunk_overlap=0)
    assert chunker.chunk([]) == []


def test_none_page_survives_round_trip() -> None:
    # DOCX/MD/TXT segments carry page=None; it must round-trip through Document metadata unchanged.
    chunker = RecursiveTextChunker(length_function=len, chunk_window=10, chunk_overlap=0)
    out = chunker.chunk([ParsedSegment(text="x" * 25, page=None)])
    assert out
    assert all(s.page is None for s in out)
