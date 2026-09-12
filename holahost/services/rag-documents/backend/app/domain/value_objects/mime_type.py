"""Uploaded document's content-sniffed MIME type."""

from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainValidationError

ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/markdown",
        "text/plain",
    }
)


@dataclass(frozen=True, slots=True)
class MimeType:
    """A document's MIME type — must be one this service has a parser for.

    Determined by content-sniffing, not the client-supplied header — but a violation
    still means "the client uploaded an unsupported file" (415
    UnsupportedMediaTypeError), so this raises `DomainValidationError`, not a plain
    `ValueError`.

    :param value: The sniffed MIME type string.
    """

    value: str

    def __post_init__(self) -> None:
        if self.value not in ALLOWED_MIME_TYPES:
            raise DomainValidationError(
                f"MIME type {self.value!r} is not supported", field="mime_type"
            )
