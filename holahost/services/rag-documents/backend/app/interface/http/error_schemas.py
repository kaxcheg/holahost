"""The published shape of every error this service can answer with (§7.6).

`application/exceptions` declares the errors themselves; this module is the same contract
as Pydantic models, which is what puts it into `docs/openapi.json` — the artifact a
consumer integrates against, diffed in CI by `make openapi-check`, so a changed `details`
key becomes a schema change someone has to approve.

Two declarations of one contract, paid deliberately: the application layer must not depend
on a serialization library. `tests/unit/interface/http/test_error_schemas.py` closes the
gap by validating every published error against its own model.

The unions are discriminated on `code`: `details` is a tagged union whose shape depends on
the error, and the identity is its tag. A consumer switches on `code`, then reads `details`
knowing its keys.

**Only this service's own errors are here.** The shared middleware's answers — `401`/`503`
from `holahost-auth`, `429` and the transport `413` from `holahost-http` — are the
platform's contract, identical behind every service, and restating them per service would
make one fact look like N. `MalformedRequestError` is delivered by `RequestIdMiddleware`
but declared by this service, so it belongs here.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    """Forbids undeclared keys, which is what lets the conformance test fail: a `details`
    that grew an unpublished key stops validating instead of quietly passing."""

    model_config = ConfigDict(extra="forbid")


_MESSAGE = Field(
    description=(
        "Human-readable, for a person reading a log or a response by hand. NOT part of "
        "the contract: do not parse it and do not show it to an end user — compose what "
        "a user sees from `code` and `details`."
    )
)


class UnsupportedMediaTypeDetails(_Strict):
    allowed: list[str] = Field(description="MIME types this service accepts.")


class InvalidPayloadDetails(_Strict):
    field: str = Field(description="Which request field failed validation.")
    limit: int | None = Field(description="That field's length limit, or null if it has none.")


class SizeDetails(_Strict):
    """Shared by every error that reports "you exceeded a size", each of which is its own
    error with its own limit — the shape is the same, the meaning of `limit` is not."""

    limit: int
    actual: int


class EmptyDocumentDetails(_Strict):
    min_chars: int = Field(description="Characters that had to be extracted, and were not.")


class NoDetails(_Strict):
    """An error whose identity is the whole message — nothing to parameterise."""


# Each model names the error it publishes in a comment, not a docstring: a docstring
# becomes that schema's `description` in the generated document, and where the original is
# declared is a fact about this repository, not about the API.
#
# `application.exceptions.UnsupportedMediaTypeError`.
class UnsupportedMediaTypeErrorBody(_Strict):
    code: Literal["UnsupportedMediaTypeError"]
    message: str = _MESSAGE
    details: UnsupportedMediaTypeDetails


# `application.exceptions.InvalidPayloadError` — raised by the use cases, and also what
# `errors.handle_validation_error` answers with when Pydantic rejects a request before
# one runs. Two raise sites, one identity and one `details` shape.
class InvalidPayloadErrorBody(_Strict):
    code: Literal["InvalidPayloadError"]
    message: str = _MESSAGE
    details: InvalidPayloadDetails


# `application.exceptions.MalformedRequestError` — the one published error no route can
# raise: `RequestIdMiddleware` answers with it before routing. Hence both its oddities — it
# is in *every* group's 422, since the header is required of every guarded route, and it
# has no row in `errors.ERROR_CONTRACT`, since its status is set where the stack is built.
class MalformedRequestErrorBody(_Strict):
    code: Literal["MalformedRequestError"]
    message: str = _MESSAGE
    details: NoDetails


# `application.exceptions.DocumentParseError`.
class DocumentParseErrorBody(_Strict):
    code: Literal["DocumentParseError"]
    message: str = _MESSAGE
    details: NoDetails


# `application.exceptions.UploadTooLargeError`.
class UploadTooLargeErrorBody(_Strict):
    code: Literal["UploadTooLargeError"]
    message: str = _MESSAGE
    details: SizeDetails


# `application.exceptions.ParsedTextTooLargeError`.
class ParsedTextTooLargeErrorBody(_Strict):
    code: Literal["ParsedTextTooLargeError"]
    message: str = _MESSAGE
    details: SizeDetails


# `application.exceptions.EmptyDocumentError`.
class EmptyDocumentErrorBody(_Strict):
    code: Literal["EmptyDocumentError"]
    message: str = _MESSAGE
    details: EmptyDocumentDetails


# `application.exceptions.TooManyChunksError`.
class TooManyChunksErrorBody(_Strict):
    code: Literal["TooManyChunksError"]
    message: str = _MESSAGE
    details: SizeDetails


# `application.exceptions.NotFoundError`.
class NotFoundErrorBody(_Strict):
    code: Literal["NotFoundError"]
    message: str = _MESSAGE
    details: NoDetails


# No exception class publishes this one — `errors._internal_error` builds it. Its
# docstring stays (and reaches the document): unlike the comments above, it says something
# a consumer needs.
class InternalErrorBody(_Strict):
    """The one out-of-contract answer. Anything this service did not publish — an
    unmapped exception, a driver failure, a defect — comes back as exactly this, with an
    empty `details` and a fixed message: the cause reaches the log, never the caller."""

    code: Literal["InternalError"]
    message: str = _MESSAGE
    details: NoDetails


def _envelope(name: str, body: Any) -> type[BaseModel]:
    """One `{"error": {...}}` wrapper around a body (or a union of bodies)."""
    return type(name, (_Strict,), {"__annotations__": {"error": body}})


_Discriminated = Field(discriminator="code")

IngestErrorResponse = _envelope(
    "IngestErrorResponse",
    Annotated[
        InvalidPayloadErrorBody
        | MalformedRequestErrorBody
        | DocumentParseErrorBody
        | ParsedTextTooLargeErrorBody
        | EmptyDocumentErrorBody
        | TooManyChunksErrorBody,
        _Discriminated,
    ],
)
SearchErrorResponse = _envelope(
    "SearchErrorResponse",
    Annotated[InvalidPayloadErrorBody | MalformedRequestErrorBody, _Discriminated],
)
ReadErrorResponse = _envelope("ReadErrorResponse", MalformedRequestErrorBody)
UploadTooLargeErrorResponse = _envelope("UploadTooLargeErrorResponse", UploadTooLargeErrorBody)
UnsupportedMediaTypeErrorResponse = _envelope(
    "UnsupportedMediaTypeErrorResponse", UnsupportedMediaTypeErrorBody
)
NotFoundErrorResponse = _envelope("NotFoundErrorResponse", NotFoundErrorBody)
InternalErrorResponse = _envelope("InternalErrorResponse", InternalErrorBody)

_INTERNAL: dict[int | str, dict[str, Any]] = {
    500: {"model": InternalErrorResponse, "description": "Out of contract — see the log."}
}
"""`500` stays: this service's own handler answers it, and a consumer needs the shape.
The platform's answers appear in none of the maps below — see the module docstring."""

INGEST_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {"model": UploadTooLargeErrorResponse, "description": "File over MAX_UPLOAD_SIZE."},
    415: {
        "model": UnsupportedMediaTypeErrorResponse,
        "description": "MIME type outside the whitelist.",
    },
    422: {"model": IngestErrorResponse, "description": "The upload could not be accepted."},
    **_INTERNAL,
}
"""`POST /documents`. `PUT /{id}` adds 404 — see `REPLACE_RESPONSES`."""

REPLACE_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": NotFoundErrorResponse, "description": "No such document for this owner."},
    **INGEST_RESPONSES,
}

SEARCH_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": NotFoundErrorResponse, "description": "No such document for this owner."},
    422: {"model": SearchErrorResponse, "description": "The query could not be accepted."},
    **_INTERNAL,
}

READ_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": NotFoundErrorResponse, "description": "No such document for this owner."},
    422: {"model": ReadErrorResponse, "description": "The transport contract was violated."},
    **_INTERNAL,
}
"""`GET /{id}` and `DELETE /{id}`: no body to validate, so the only 422 is the edge's."""
