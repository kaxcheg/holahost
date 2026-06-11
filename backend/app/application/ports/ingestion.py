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

        Args:
            text: Source text to chunk.

        Returns:
            Chunk strings; ordinal = list index (§7.4 / §9.4).
        """
        ...
