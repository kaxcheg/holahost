"""What this service publishes, and the status each error answers with.

Two declarations and nothing else, which is the point: the machinery around them — the MRO
walk that answers an unpublished subclass as its published ancestor, the closed vocabulary
that turns everything else into `500 InternalError` with an empty body, the failure log,
the header echo Starlette's outermost handler would otherwise drop — belongs to every
service equally and lives in `holahost_http`. Both are passed to `create_edge_app` as data;
nothing here wraps the platform's registration, because the function that consumes them
lives in that same package.

An error the middleware answers with before routing has no row here: its status is an
argument where the stack is assembled (`app.py`), and a row would be a second source for
the same number.

`error_schemas.py` turns this table into the response models the routes declare, so
`docs/openapi.json` is generated from it and CI diffs any change.
"""

from __future__ import annotations

from holahost_http import ErrorContract, InvalidPayloadError, NotFoundError

ERROR_CONTRACT: ErrorContract = {
    # `InvalidPayloadError` is required: it is what the framework's own request validation
    # is answered with, and `create_edge_app` refuses a contract without it.
    InvalidPayloadError: 422,
    NotFoundError: 404,
}
"""422 rather than 400 for a rejected field: by RFC 9110 §15.5.1 a 400 is broken syntax or
framing, while 422 (RFC 4918 §11.2) is a syntactically correct request whose content could
not be processed. Reserve 400 for an HTTP framing violation."""

SILENT_500_TYPES: tuple[type[Exception], ...] = ()
"""Types answered `500` through an ordinary handler rather than Starlette's bare-`Exception`
one, which is bound to `ServerErrorMiddleware` and re-raises after writing the response —
so uvicorn prints an unstructured traceback outside the JSON log and outside its scrubbing.
A service's own domain-invariant error is the usual member: reaching the interface layer
untranslated is a defect either way."""
