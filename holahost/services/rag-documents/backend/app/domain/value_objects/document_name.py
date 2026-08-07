"""Document display name."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from domain.exceptions import DomainValidationError

MAX_DOCUMENT_NAME_LENGTH = 200  # spec §3.7


@dataclass(frozen=True, slots=True)
class DocumentName:
    """A document's display name — 1..MAX_DOCUMENT_NAME_LENGTH chars, no control chars (spec §4.1).

    :param value: The name, taken directly from the request body.
    """

    value: str

    def __post_init__(self) -> None:
        stripped = self.value.strip()
        object.__setattr__(self, "value", stripped)
        if not stripped:
            raise DomainValidationError("DocumentName must not be empty", field="name")
        if len(stripped) > MAX_DOCUMENT_NAME_LENGTH:
            raise DomainValidationError(
                f"DocumentName length exceeds {MAX_DOCUMENT_NAME_LENGTH}", field="name"
            )
        if any(unicodedata.category(ch) == "Cc" for ch in stripped):
            raise DomainValidationError("DocumentName contains control characters", field="name")
