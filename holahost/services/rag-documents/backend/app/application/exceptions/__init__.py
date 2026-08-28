"""The errors this service throws at its boundary — one class per error (spec §7.6).

Each class is the whole contract for the error it names. Its **identity** on the wire is
its class name, verbatim (`PlatformError.code` returns `type(self).__name__`), and the
**shape of its `details`** is what `details_dict()` returns. Nothing else about an error
is contractual:

- the `message` is for a person reading a log or a curl, never for a consumer to parse —
  a caller composes what it shows a user from `details`;
- the HTTP status is a projection the interface layer applies (`interface/http/errors.py`),
  not a property of the error. That is why two errors may map to the same status and why
  changing a status is not a change to this file.

There are no shared identities. `UploadTooLargeError` and `ParsedTextTooLargeError` used
to answer with one code, and so did `DocumentParseError`/`MalformedRequestError`, on the
argument that the code should name "the fact for the client". It does not: a consumer
builds its message from `details`, so what the identity has to name is *which error the
service threw* — and those were four different errors, distinguishable only by digging
into a `details` value (`field == "file"`) or by reading the status. One error, one
identity.
"""

from __future__ import annotations

from collections.abc import Mapping

from holahost_http import PlatformError


class ApplicationError(PlatformError):
    """Base for every application-layer, HTTP-facing exception.

    Inherits the platform base purely for the envelope contract it defines (a derived
    `code` + `details_dict()`) — that is what lets the shared envelope builder render any
    of these. The errors below stay this service's own.

    Never thrown itself, and deliberately absent from the interface layer's status table:
    an instance of the base, or of a subclass nobody put in that table, is by
    construction not one of the errors this service publishes. The handler answers those
    with the out-of-contract `500 InternalError` and an empty body.
    """


class UnsupportedMediaTypeError(ApplicationError):
    """The file's MIME type is not supported.

    Raised both by the use case (claimed type fails the whitelist check, via
    `domain.value_objects.mime_type.MimeType`) and directly by `FileParser.parse`
    (sniffed content does not match the claim) — one class, two raise sites.
    """

    def __init__(self, allowed: tuple[str, ...]) -> None:
        super().__init__("unsupported media type")
        self.allowed = allowed

    def details_dict(self) -> Mapping[str, object]:
        return {"allowed": list(self.allowed)}


class InvalidPayloadError(ApplicationError):
    """A request field failed validation (document name, search query).

    `limit` is always in `details`, `None` included: one identity answers with one set of
    keys, so `details.limit` is never a `KeyError` on some raise sites and a value on
    others. `None` says "this field has no length limit", which a caller can read; an
    absent key says nothing at all.
    """

    def __init__(self, field: str, limit: int | None = None) -> None:
        super().__init__(f"invalid payload: {field}")
        self.field = field
        self.limit = limit

    def details_dict(self) -> Mapping[str, object]:
        return {"field": self.field, "limit": self.limit}


class MalformedRequestError(ApplicationError):
    """A request violated the transport contract, with nothing disclosed about how.

    Empty `details` on purpose: this is the only error answered *before* authentication.
    Every other one goes to a caller the service has already identified and who is
    entitled to know which field it got wrong; this one goes to a caller that, by
    construction, arrived by a path it was not meant to — both real entry paths attach
    `X-Request-ID` unconditionally. Naming the header would hand exactly that caller the
    one hint needed to get past the check. Same discipline §7.6 applies to `401`: the
    reason is logged, never returned.

    The identity itself discloses nothing beyond "the transport contract was violated",
    which the empty `details` already gave away.
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

    A different error from `UploadTooLargeError`, not the same one at a later moment: the
    limit it names measures extracted characters, not uploaded bytes, and a caller that
    hits it sent a file the service was willing to read. The interface layer maps this to
    422 and the raw-size one to 413 — resolving §7.6's table (413 for both) in favour of
    US-R01's more specific AC, approved by user, see clarifications.md.
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

    Its own identity, and empty `details` because the identity is the whole message: the
    caller's remedy is to re-export or re-upload the file, which no parameter refines. It
    used to answer as `InvalidPayloadError` with `{"field": "file"}`, so a consumer had to
    read a `details` value to learn which of three unrelated failures it had hit.

    Deliberately *not* `EmptyDocumentError`: that one means the file was read
    successfully but lacks content, a different fact with a different fix (add content,
    vs. re-export a valid file).
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
    document is never disclosed. Empty `details`: there is nothing to say that would not
    say which of the two it was.
    """

    def __init__(self) -> None:
        super().__init__("document not found")
