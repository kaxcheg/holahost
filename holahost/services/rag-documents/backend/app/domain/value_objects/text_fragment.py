"""A fragment of extracted text with page provenance."""

from __future__ import annotations

from dataclasses import dataclass

from domain.value_objects.page_number import PageNumber


@dataclass(frozen=True, slots=True)
class TextFragment:
    """Text with provenance — used at both pipeline stages: parser output (page-sized)
    and chunker output (window-sized) (spec §4.1).

    :param text: The fragment's text; non-empty after `strip`.
    :param page: The source page, or `PageNumber(None)` for pageless formats.
    """

    text: str
    page: PageNumber

    def __post_init__(self) -> None:
        # Parser/chunker output, not client input directly — internal defect
        # if empty, so plain ValueError (the AC-level "document is empty"
        # check operates on the whole document's extracted text, not a
        # single fragment, and is a use-case concern, not this VO's).
        if not self.text.strip():
            raise ValueError("TextFragment text must not be empty")
