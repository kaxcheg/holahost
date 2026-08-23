"""Application-layer exceptions, mapped to the ERR_* wire taxonomy (spec §7.6).

Carries `code` and `details_dict()` only — no HTTP status. Status is an HTTP-protocol
concept and belongs to the interface layer's error handler (§3.2, ticket R-22, not yet
built), which maps exception type -> status (FastAPI's own idiom:
`@app.exception_handler(SpecificType)`), not `code` -> status — `ERR_PAYLOAD_TOO_LARGE`
needs two different statuses depending on which of `UploadTooLargeError`/
`ParsedTextTooLargeError` was raised, which type-based dispatch handles for free.
"""

from __future__ import annotations

from collections.abc import Mapping

from holahost_http import PlatformError


class ApplicationError(PlatformError):
    """Base for every application-layer, HTTP-facing exception.

    Inherits the platform base purely for the envelope contract it defines (`code` +
    `details_dict()`, both already the shape used here) — that is what lets the shared
    envelope builder render any of these. The taxonomy below stays this service's own:
    the library owns no codes except the two its own middleware raise.
    """


class UnsupportedMediaTypeError(ApplicationError):
    """The file's MIME type is not supported.

    Raised both by the use case (claimed type fails the whitelist check, via
    `domain.value_objects.mime_type.MimeType`) and directly by `FileParser.parse`
    (sniffed content does not match the claim) — one class, two raise sites.
    """

    code = "ERR_UNSUPPORTED_MEDIA_TYPE"

    def __init__(self, allowed: tuple[str, ...]) -> None:
        super().__init__("unsupported media type")
        self.allowed = allowed

    def details_dict(self) -> Mapping[str, object]:
        return {"allowed": list(self.allowed)}


class InvalidPayloadError(ApplicationError):
    """A request field failed validation (document name, search query)."""

    code = "ERR_INVALID_PAYLOAD"

    def __init__(self, field: str, limit: int | None = None) -> None:
        super().__init__(f"invalid payload: {field}")
        self.field = field
        self.limit = limit

    def details_dict(self) -> Mapping[str, object]:
        details: dict[str, object] = {"field": self.field}
        if self.limit is not None:
            details["limit"] = self.limit
        return details


class MalformedRequestError(ApplicationError):
    """A request violated the transport contract, with nothing disclosed about how.

    Same wire code as `InvalidPayloadError` and deliberately **no** `details`: this is the
    only `ERR_INVALID_PAYLOAD` answered *before* authentication. Every other one goes to a
    caller the service has already identified and who is entitled to know which field it
    got wrong; this one goes to a caller that, by construction, arrived by a path it was
    not meant to — both real entry paths attach `X-Request-ID` unconditionally. Naming the
    header in the body would hand exactly that caller the one hint needed to get past this
    check. Same discipline §7.6 already applies to `401`: the reason is logged, never
    returned.
    """

    code = "ERR_INVALID_PAYLOAD"

    def __init__(self) -> None:
        super().__init__("invalid request")


class UploadTooLargeError(ApplicationError):
    """The raw uploaded file exceeds `MAX_UPLOAD_SIZE`, checked before parsing.

    Interface layer maps this to 413 (raw byte-size gate, runs before parsing).
    """

    code = "ERR_PAYLOAD_TOO_LARGE"

    def __init__(self, limit: int, actual: int) -> None:
        super().__init__("upload too large")
        self.limit = limit
        self.actual = actual

    def details_dict(self) -> Mapping[str, object]:
        return {"limit": self.limit, "actual": self.actual}


class ParsedTextTooLargeError(ApplicationError):
    """The parsed text exceeds `MAX_PARSED_TEXT_LENGTH`, checked after parsing.

    Same wire `code` as `UploadTooLargeError`; interface layer maps this one to 422
    (a post-parse content check, grouped with `EmptyDocumentError`/
    `TooManyChunksError`) instead of 413 — resolves a conflict between spec §7.6's
    table (413 for both) and US-R01's AC (422 for this case) in favor of the more
    specific AC, approved by user, see clarifications.md.
    """

    code = "ERR_PAYLOAD_TOO_LARGE"

    def __init__(self, limit: int, actual: int) -> None:
        super().__init__("parsed text too large")
        self.limit = limit
        self.actual = actual

    def details_dict(self) -> Mapping[str, object]:
        return {"limit": self.limit, "actual": self.actual}


class EmptyDocumentError(ApplicationError):
    """Fewer than `MIN_EXTRACTED_TEXT_CHARS` characters were extracted from the file."""

    code = "ERR_EMPTY_DOCUMENT"

    def __init__(self, min_chars: int) -> None:
        super().__init__("document has no usable extracted text")
        self.min_chars = min_chars

    def details_dict(self) -> Mapping[str, object]:
        return {"min_chars": self.min_chars}


class DocumentParseError(ApplicationError):
    """The file is corrupted or could not be parsed at all.

    Wire code `ERR_INVALID_PAYLOAD`, not a dedicated code (none exists in §7.6): the
    uploaded `file` field's content isn't a valid instance of the claimed format —
    the same "you sent me a bad field" fact as any other `InvalidPayloadError` cause
    (empty name, over-length query). Deliberately *not* `ERR_EMPTY_DOCUMENT`: that
    code means the file was read successfully but lacks content, a different fact
    with a different fix (add content, vs. re-export/re-upload a valid file) — see
    `EmptyDocumentError`. Kept as its own class rather than raising a plain
    `InvalidPayloadError` because §8.0's port contract names it as `FileParser`'s
    own distinct raise.
    """

    code = "ERR_INVALID_PAYLOAD"

    def __init__(self) -> None:
        super().__init__("document could not be parsed")

    def details_dict(self) -> Mapping[str, object]:
        return {"field": "file"}


class TooManyChunksError(ApplicationError):
    """The document produced more than `MAX_CHUNKS_PER_DOCUMENT` chunks."""

    code = "ERR_TOO_MANY_CHUNKS"

    def __init__(self, limit: int, actual: int) -> None:
        super().__init__("too many chunks")
        self.limit = limit
        self.actual = actual

    def details_dict(self) -> Mapping[str, object]:
        return {"limit": self.limit, "actual": self.actual}


class NotFoundError(ApplicationError):
    """The document does not exist, or belongs to another owner (US-R06, A-13).

    The two cases are indistinguishable on purpose — existence of another subject's
    document is never disclosed. No `resource` field: §7.6's table shows `details: —`
    for `ERR_NOT_FOUND`.
    """

    code = "ERR_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("document not found")
