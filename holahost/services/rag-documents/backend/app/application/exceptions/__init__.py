"""The errors this service throws at its boundary — one class per error.

Each class is the whole contract for the error it names: its **identity** on the wire is
its class name, verbatim (`PlatformError.code`), and the shape of its **`details`** is
what `details_dict()` returns. Nothing else is contractual — the `message` is for a
person reading a log, and the HTTP status is a projection applied by
`interface/http/errors.py`, which is why two errors may share one status and why
changing a status is not a change to this file.

No two errors share an identity: a consumer builds its message from `details`, so what
the identity has to name is which error the service threw, not the category it falls in.
"""

from __future__ import annotations

from collections.abc import Mapping

from holahost_http import (
    InvalidPayloadError,
    MalformedRequestError,
    NotFoundError,
    PlatformError,
)

# Three of the errors this service throws are the platform's, not its own: every service
# rejects a field, refuses a request that broke the transport contract, and answers for a
# resource that is absent or another subject's — with the same identity and the same
# `details` each time. They are re-exported here so the rest of the service goes on
# importing every error it raises from one place, and so their rows in `ERROR_CONTRACT`
# read like the others'.
__all__ = [
    "ApplicationError",
    "DocumentParseError",
    "EmptyDocumentError",
    "InvalidPayloadError",
    "MalformedRequestError",
    "NotFoundError",
    "ParsedTextTooLargeError",
    "TooManyChunksError",
    "UnsupportedMediaTypeError",
    "UploadTooLargeError",
]


class ApplicationError(PlatformError):
    """Base for every application-layer, HTTP-facing exception.

    Inherits the platform base for the envelope contract it defines (`code` +
    `details_dict()`); the errors below stay this service's own.

    Never thrown itself, and deliberately absent from the interface layer's status table:
    an instance of the base, or of a subclass nobody published, is by construction not one
    of this service's errors and is answered `500 InternalError` with an empty body.
    """


class UnsupportedMediaTypeError(ApplicationError):
    """The file's MIME type is not supported.

    Raised by the use case (claimed type fails the whitelist) and by `FileParser.parse`
    (sniffed content does not match the claim) — one class, two raise sites.
    """

    def __init__(self, allowed: tuple[str, ...]) -> None:
        super().__init__("unsupported media type")
        self.allowed = allowed

    def details_dict(self) -> Mapping[str, object]:
        return {"allowed": list(self.allowed)}


class UploadTooLargeError(ApplicationError):
    """The raw uploaded file exceeds `MAX_UPLOAD_SIZE`, checked before parsing."""

    def __init__(self, limit: int, actual: int) -> None:
        super().__init__("upload too large")
        self.limit = limit
        self.actual = actual

    def details_dict(self) -> Mapping[str, object]:
        return {"limit": self.limit, "actual": self.actual}


class ParsedTextTooLargeError(ApplicationError):
    """The parsed text exceeds `MAX_PARSED_TEXT_LENGTH`, checked after parsing.

    A different error from `UploadTooLargeError`, not the same one later: it measures
    extracted characters rather than uploaded bytes, and a caller that hits it sent a file
    the service was willing to read. Mapped to 422 against the raw-size error's 413,
    because "we read it and it was too big" is a different fact from "we refused to read it".
    """

    def __init__(self, limit: int, actual: int) -> None:
        super().__init__("parsed text too large")
        self.limit = limit
        self.actual = actual

    def details_dict(self) -> Mapping[str, object]:
        return {"limit": self.limit, "actual": self.actual}


class EmptyDocumentError(ApplicationError):
    """Fewer than `MIN_EXTRACTED_TEXT_CHARS` characters were extracted from the file."""

    def __init__(self, min_chars: int) -> None:
        super().__init__("document has no usable extracted text")
        self.min_chars = min_chars

    def details_dict(self) -> Mapping[str, object]:
        return {"min_chars": self.min_chars}


class DocumentParseError(ApplicationError):
    """The file is corrupted or could not be parsed at all.

    Empty `details`: the caller's remedy is to re-export or re-upload the file, which no
    parameter refines. Deliberately not `EmptyDocumentError`, which means the file was
    read successfully but lacks content — a different fact with a different fix.
    """

    def __init__(self) -> None:
        super().__init__("document could not be parsed")


class TooManyChunksError(ApplicationError):
    """The document produced more than `MAX_CHUNKS_PER_DOCUMENT` chunks."""

    def __init__(self, limit: int, actual: int) -> None:
        super().__init__("too many chunks")
        self.limit = limit
        self.actual = actual

    def details_dict(self) -> Mapping[str, object]:
        return {"limit": self.limit, "actual": self.actual}
