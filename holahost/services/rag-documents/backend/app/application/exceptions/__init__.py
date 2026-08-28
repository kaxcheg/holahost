"""The errors this service throws at its boundary — one class per error (spec §7.6).

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

from holahost_http import PlatformError


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


class InvalidPayloadError(ApplicationError):
    """A request field failed validation (document name, search query).

    `limit` is always present, `None` included: one identity answers with one set of keys,
    and `None` says "this field has no length limit", which a caller can read.
    """

    def __init__(self, field: str, limit: int | None = None) -> None:
        super().__init__(f"invalid payload: {field}")
        self.field = field
        self.limit = limit

    def details_dict(self) -> Mapping[str, object]:
        return {"field": self.field, "limit": self.limit}


class MalformedRequestError(ApplicationError):
    """A request violated the transport contract, with nothing disclosed about how.

    Empty `details` on purpose: this is the only error answered *before* authentication,
    so it goes to a caller that, by construction, arrived by a path it was not meant to —
    both real entry paths attach `X-Request-ID` unconditionally. Naming the header would
    hand exactly that caller the hint needed to get past the check. Same discipline §7.6
    applies to `401`: the reason is logged, never returned.
    """

    def __init__(self) -> None:
        super().__init__("invalid request")


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
    resolving §7.6's table in favour of US-R01's more specific AC.
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


class NotFoundError(ApplicationError):
    """The document does not exist, or belongs to another owner (US-R06, A-13).

    The two cases are indistinguishable on purpose — existence of another subject's
    document is never disclosed — which is also why `details` is empty.
    """

    def __init__(self) -> None:
        super().__init__("document not found")
