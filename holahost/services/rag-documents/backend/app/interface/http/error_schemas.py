"""The published shape of every error this service can answer with.

`application/exceptions` declares the errors themselves; this module is the same contract
as Pydantic models, which is what puts it into `docs/openapi.json` — the artifact a
consumer integrates against, diffed in CI by `make openapi-check`, so a changed `details`
key becomes a schema change someone has to approve.

Two declarations of one contract, paid deliberately: the application layer must not depend
on a serialization library. `tests/unit/interface/http/test_error_schemas.py` closes the
gap by validating every published error against its own model.

The unions are discriminated on `code`: `details` is a tagged union whose shape depends on
the error, and the identity is its tag. A consumer switches on `code`, then reads `details`
knowing its keys. `message` is in no model — it rides the wire for a person reading a log
by hand, and publishing it would invite exactly the parsing the contract rules out.

**Only this service's own errors are here.** The platform's — the envelope wrapper, the
empty `details`, `InvalidPayloadError`, `MalformedRequestError`, `NotFoundError` and
`InternalError` — come from `holahost_http.error_schemas`; its middleware's answers
(`401`/`503`, `429`, the transport `413`) are described nowhere per-service, because
restating one fact behind N services makes it N facts that drift.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from holahost_http.error_schemas import (
    INTERNAL_RESPONSES,
    InvalidPayloadErrorBody,
    MalformedRequestErrorBody,
    NoDetails,
    NotFoundErrorBody,
    Strict,
    discriminated,
    envelope,
)
from pydantic import Field


class UnsupportedMediaTypeDetails(Strict):
    allowed: list[str] = Field(description="MIME types this service accepts.")


class SizeDetails(Strict):
    """Shared by every error that reports "you exceeded a size", each of which is its own
    error with its own limit — the shape is the same, the meaning of `limit` is not."""

    limit: int
    actual: int


class EmptyDocumentDetails(Strict):
    min_chars: int = Field(description="Characters that had to be extracted, and were not.")


# Each model names the error it publishes in a comment, not a docstring: a docstring
# becomes that schema's `description` in the generated document, and where the original is
# declared is a fact about this repository, not about the API.
#
# `application.exceptions.UnsupportedMediaTypeError`.
class UnsupportedMediaTypeErrorBody(Strict):
    code: Literal["UnsupportedMediaTypeError"]
    details: UnsupportedMediaTypeDetails


# `application.exceptions.DocumentParseError`.
class DocumentParseErrorBody(Strict):
    code: Literal["DocumentParseError"]
    details: NoDetails


# `application.exceptions.UploadTooLargeError`.
class UploadTooLargeErrorBody(Strict):
    code: Literal["UploadTooLargeError"]
    details: SizeDetails


# `application.exceptions.ParsedTextTooLargeError`.
class ParsedTextTooLargeErrorBody(Strict):
    code: Literal["ParsedTextTooLargeError"]
    details: SizeDetails


# `application.exceptions.EmptyDocumentError`.
class EmptyDocumentErrorBody(Strict):
    code: Literal["EmptyDocumentError"]
    details: EmptyDocumentDetails


# `application.exceptions.TooManyChunksError`.
class TooManyChunksErrorBody(Strict):
    code: Literal["TooManyChunksError"]
    details: SizeDetails


IngestErrorResponse = envelope(
    "IngestErrorResponse",
    Annotated[
        # `MalformedRequestErrorBody` is in every group's 422: `RequestIdMiddleware`
        # answers with it on every guarded route, before this service's own validation
        # has anything to say.
        InvalidPayloadErrorBody
        | MalformedRequestErrorBody
        | DocumentParseErrorBody
        | ParsedTextTooLargeErrorBody
        | EmptyDocumentErrorBody
        | TooManyChunksErrorBody,
        discriminated,
    ],
)
SearchErrorResponse = envelope(
    "SearchErrorResponse",
    Annotated[InvalidPayloadErrorBody | MalformedRequestErrorBody, discriminated],
)
ReadErrorResponse = envelope("ReadErrorResponse", MalformedRequestErrorBody)
UploadTooLargeErrorResponse = envelope("UploadTooLargeErrorResponse", UploadTooLargeErrorBody)
UnsupportedMediaTypeErrorResponse = envelope(
    "UnsupportedMediaTypeErrorResponse", UnsupportedMediaTypeErrorBody
)
NotFoundErrorResponse = envelope("NotFoundErrorResponse", NotFoundErrorBody)

INGEST_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {"model": UploadTooLargeErrorResponse, "description": "File over MAX_UPLOAD_SIZE."},
    415: {
        "model": UnsupportedMediaTypeErrorResponse,
        "description": "MIME type outside the whitelist.",
    },
    422: {"model": IngestErrorResponse, "description": "The upload could not be accepted."},
    **INTERNAL_RESPONSES,
}
"""`POST /documents`. `PUT /{id}` adds 404 — see `REPLACE_RESPONSES`."""

REPLACE_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": NotFoundErrorResponse, "description": "No such document for this owner."},
    **INGEST_RESPONSES,
}

SEARCH_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": NotFoundErrorResponse, "description": "No such document for this owner."},
    422: {"model": SearchErrorResponse, "description": "The query could not be accepted."},
    **INTERNAL_RESPONSES,
}

READ_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": NotFoundErrorResponse, "description": "No such document for this owner."},
    422: {"model": ReadErrorResponse, "description": "The transport contract was violated."},
    **INTERNAL_RESPONSES,
}
"""`GET /{id}` and `DELETE /{id}`: no body to validate, so the only 422 is the edge's."""
