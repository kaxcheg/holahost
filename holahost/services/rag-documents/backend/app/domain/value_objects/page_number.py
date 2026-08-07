"""A chunk's source page, when the format has pages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageNumber:
    """Provenance page number — >= 1 if set, `None` for pageless formats (spec §4.1).

    :param value: The 1-based page number, or `None`.
    """

    value: int | None

    def __post_init__(self) -> None:
        # Parser-computed, not client input — an out-of-range value is an
        # internal defect (parser bug), so this stays a plain ValueError.
        if self.value is not None and self.value < 1:
            raise ValueError("PageNumber must be at least 1 when set")
