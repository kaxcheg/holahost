"""Protocols for parsing uploaded files into text and splitting text into chunks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from domain.exceptions import DomainValidationError
from domain.value_objects.mime_type import MimeType
from domain.value_objects.page_number import PageNumber


@dataclass(frozen=True, slots=True)
class TextFragment:
    """Text with provenance — used at both pipeline stages: parser output (page-sized)
    and chunker output (window-sized).

    An application-layer pipeline-transit type, not a domain value object: it never
    becomes a field of `Document` or `Chunk` (those flatten `text`/`page` as separate
    fields directly) — it exists only to shuttle data between `FileParser` and
    `TextChunker` during orchestration.

    :param text: The fragment's text; non-empty after `strip`.
    :param page: The source page, or `PageNumber(None)` for pageless formats.
    """

    text: str
    page: PageNumber

    def __post_init__(self) -> None:
        # Parser/chunker output, not client input directly — internal defect if
        # empty, so `field` stays None.
        if not self.text.strip():
            raise DomainValidationError("TextFragment text must not be empty")


class FileParser(Protocol):
    """Extracts page-provenanced text fragments from raw file bytes.

    Implementations sniff the actual content rather than trusting a caller-supplied MIME
    type, and parse in-process — no external utilities (§3.8).
    """

    def parse(self, content: bytes, mime_type: MimeType) -> list[TextFragment]:
        """Parse ``content`` into page-sized text fragments.

        Args:
            content: Raw file bytes.
            mime_type: The claimed MIME type, used to select a parser backend.

        Returns:
            One fragment per page (or a single fragment for page-less formats).

        Raises:
            UnsupportedMediaTypeError: the actual content does not match ``mime_type``.
            DocumentParseError: the file is corrupted or cannot be parsed.
        """
        ...


class TextChunker(Protocol):
    """Splits page-sized fragments into window-sized chunks for embedding.

    A chunk never crosses the boundary of the fragment it was cut from, so each chunk
    keeps the page provenance of its source fragment.
    """

    def split(self, fragments: list[TextFragment]) -> list[TextFragment]:
        """Split ``fragments`` into chunk-sized fragments.

        Args:
            fragments: Page-sized fragments, in document order.

        Returns:
            Chunk-sized fragments, in document order, each carrying its source page.
        """
        ...
