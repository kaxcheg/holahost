from __future__ import annotations

from typing import Protocol

from domain.value_objects.parsed_segment import ParsedSegment


class FileParser(Protocol):
    """Port: extract text segments from an uploaded document (spec §8.2.1)."""

    def parse(self, file_bytes: bytes, mime_type: str) -> list[ParsedSegment]:
        """Parse raw file bytes into ordered text segments with page provenance.

        Args:
            file_bytes: Raw uploaded file content.
            mime_type: MIME type used to route to the concrete parser.

        Returns:
            Segments in document order; PDF yields one segment per page (``page`` 0-based),
            other formats yield a single segment with ``page=None``.

        Raises:
            UnsupportedMediaTypeError: the MIME type is not supported (defense-in-depth, §9.0).
            InvalidPayloadError: the file is corrupt / undecodable (``field='file'``, §9.0).
        """
        ...


class TextChunker(Protocol):
    """Port: split parsed segments into overlapping chunks, preserving page provenance (spec §8.2.1)."""

    def chunk(self, segments: list[ParsedSegment]) -> list[ParsedSegment]:
        """Split each segment into token-bounded chunks.

        Invariant (enforced by the impl): every returned chunk fits the embedding model's max input
        length (``max_chunk_tokens``). The chunker's token window MUST be ``<= max_chunk_tokens``;
        otherwise the embedder silently truncates over-long chunks and retrieval quality degrades
        (§2.5). The application layer relies on this contract — it has no tokenizer to re-check.

        Args:
            segments: Parsed segments (text + optional source page).

        Returns:
            Chunk segments in document order; each carries its source segment's ``page``;
            ordinal = list index (§7.4 / §9.4).
        """
        ...
