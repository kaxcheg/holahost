from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSegment:
    """A unit of extracted document text with optional source-page provenance (spec §2.5, C-05/C-06).

    Transient pipeline carrier at TWO boundaries: ``FileParser.parse`` output (one segment per source
    unit — per PDF page, or a single whole-document segment for DOCX/MD/TXT) and ``TextChunker.chunk``
    output (one segment per chunk, ``page`` inherited from its source segment). ``page`` is the 0-based
    source page for PDF inputs and ``None`` when the format has no intrinsic pagination.

    Args:
        text: Extracted text for this segment.
        page: 0-based source page (PDF), or ``None`` when not page-derived.
    """

    text: str
    page: int | None
