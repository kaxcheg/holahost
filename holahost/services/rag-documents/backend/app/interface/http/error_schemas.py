"""The published shape of every error this service can answer with (§7.6).

`application/exceptions` declares the errors themselves — identity (its class name) and
`details` shape (what `details_dict()` returns). This module is the same contract
expressed as Pydantic models, which is what puts it into `docs/openapi.json`: the
generated schema is the artifact a consumer integrates against, and `make openapi-check`
diffs it in CI, so renaming an error class or changing a `details` key stops being a
silent refactor and becomes a schema change someone has to approve.

Two declarations of one contract is a cost, paid deliberately: the application layer must
not depend on a serialization library, and the wire is the interface layer's business.
`tests/unit/interface/http/test_error_schemas.py` closes the gap — it asserts that every
published error validates against its own model, so the two cannot drift.

The unions are discriminated on `code`, which is exactly what `code` is for: `details` is
a tagged union whose shape depends on which error was thrown, and the identity is its
tag. A consumer switches on `code`, then reads `details` knowing its keys. Each `Literal`
below therefore repeats an error class's name — which is what a reader should be able to
grep straight back to, and what `test_error_schemas` asserts stays equal to it.

**Only this service's own errors are here.** What the shared middleware answers with —
`401`/`503` from `holahost-auth`, `429 RateLimitExceededError` and the transport
`413 PayloadTooLargeError` from `holahost-http` — is the platform's contract, identical
for every service behind the same edge, and restating it in each service's document
would make one fact look like N. `MalformedRequestError` is the exception that proves the
rule: `RequestIdMiddleware` delivers it, but the error is this service's own (its
identity and its mute `details` are declared in `application/exceptions`), so it is here.

`InternalError` is the one identity with no class behind it — see `errors._internal_error`
for why there is deliberately none to derive it from.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    """Every model here forbids undeclared keys, which is what makes the conformance
    test in `tests/unit/interface/http/test_error_schemas.py` able to fail: a `details`
    that grew a key nobody published stops validating instead of quietly passing."""

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


# Each model below names the error it publishes, in a comment rather than a docstring: a
# model's docstring becomes that schema's `description` in the generated document, and
# where the original is declared is a fact about this repository, not about the API. The
# name in the comment is the same one the class publishes as `code`, so a reader lands on
# the declaration in one grep.
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
# raise: `RequestIdMiddleware` answers with it before routing (`edge.MISSING_REQUEST_ID_ERROR`).
# Hence both its oddities — it is in *every* group's 422, because the header is required of
# every guarded route, and it has no row in `errors.ERROR_CONTRACT`, because its status is
# an argument at the point the stack is assembled.
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


# Nothing to reference: no exception class publishes this one — `errors._internal_error`
# builds it. Its docstring is kept (and does reach the document) because unlike the
# comments above it says something a consumer needs: what this answer means.
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
"""`500` stays: it is this service's own handler answering, and a consumer needs the
shape. The platform's own answers (`401`, `503`, `429`, and the transport `413`) do not
appear in any of the maps below — see the module docstring."""

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
