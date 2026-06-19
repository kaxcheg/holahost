from __future__ import annotations

from typing import Protocol


class FileParser(Protocol):
    """Port: extract plain text from an uploaded document (spec §8.2.1)."""

    def parse(self, file_bytes: bytes, mime_type: str) -> str:
        """Parse raw file bytes into plain text.

        Args:
            file_bytes: Raw uploaded file content.
            mime_type: MIME type used to route to the concrete parser.

        Returns:
            Extracted plain text.
        """
        ...


class TextChunker(Protocol):
    """Port: split text into overlapping chunks (spec §8.2.1)."""

    def chunk(self, text: str) -> list[str]:
        """Split text into ordered chunk strings.

        Invariant (enforced by the impl): every returned chunk fits within the embedding model's
        max input length (``max_chunk_tokens``). The chunker's token window MUST be configured
        ``<= max_chunk_tokens``; otherwise the embedder silently truncates over-long chunks and
        retrieval quality degrades (§2.5). The application layer relies on this contract — it has no
        tokenizer to re-check chunk length at runtime.

        Args:
            text: Source text to chunk.

        Returns:
            Chunk strings; ordinal = list index (§7.4 / §9.4).
        """
        ...
