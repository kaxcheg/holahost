"""What this service publishes, and the status each error answers with (spec §7.6).

Two declarations and nothing else, which is the point: the machinery around them — the MRO
walk that answers an unpublished subclass as its published ancestor, the closed vocabulary
that turns everything else into `500 InternalError` with an empty body, the failure log,
the header echo Starlette's outermost handler would otherwise drop — belongs to every
service equally and lives in `holahost_http`. Both are passed to `create_edge_app` as data;
nothing here wraps the platform's registration, because the function that consumes them
lives in that same package and a wrapper would only leave and come straight back.

`MalformedRequestError` has no row here despite being an error this service answers with:
`RequestIdMiddleware` produces it before routing, so its status is an argument where the
stack is assembled (`app.py`), and a row would be a second source for the same number.

`error_schemas.py` turns this table into the response models the routes declare, so
`docs/openapi.json` is generated from it and CI diffs any change.
"""

from __future__ import annotations

from holahost_http import ErrorContract, InvalidPayloadError, NotFoundError

from application.exceptions import (
    DocumentParseError,
    EmptyDocumentError,
    ParsedTextTooLargeError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
    UploadTooLargeError,
)
from domain.exceptions import DomainValidationError

ERROR_CONTRACT: ErrorContract = {
    UnsupportedMediaTypeError: 415,
    InvalidPayloadError: 422,
    DocumentParseError: 422,
    UploadTooLargeError: 413,
    ParsedTextTooLargeError: 422,
    EmptyDocumentError: 422,
    TooManyChunksError: 422,
    NotFoundError: 404,
}
"""`InvalidPayloadError` is 422 rather than 400: by RFC 9110 §15.5.1 a 400 is broken
syntax or framing, while 422 (RFC 4918 §11.2) is a syntactically correct request whose
content could not be processed. 400 is used by no mapping here — it stays reserved for an
HTTP framing violation, which this service does not produce."""

SILENT_500_TYPES: tuple[type[Exception], ...] = (DomainValidationError,)
"""Answered `500` with an empty body, through an ordinary handler.

A domain invariant that reached the interface layer untranslated is a defect either way:
an unset `field` is internal by definition, and a `field`-carrying one means the use case
owing it a §7.6 error did not produce one. Named rather than left to the bare-`Exception`
handler, which Starlette binds to `ServerErrorMiddleware` — that one re-raises after
writing the response, so uvicorn prints an unstructured traceback outside the JSON log and
outside its scrubbing."""
