"""The published shape of every error this service can answer with.

`application/exceptions` declares the errors themselves; this module is the same contract as
Pydantic models, which is what puts it into `docs/openapi.json` — the artifact a consumer
integrates against, diffed in CI by `make openapi-check`, so a changed `details` key becomes
a schema change someone has to approve.

Two declarations of one contract, paid deliberately: the application layer must not depend
on a serialization library. A test validating every published error against its own model is
what closes the gap.

The unions are discriminated on `code`: `details` is a tagged union whose shape depends on
the error, and the identity is its tag. A consumer switches on `code`, then reads `details`
knowing its keys. `message` is in no model — it rides the wire for a person reading a log by
hand, and publishing it would invite parsing it.

**Only this service's own errors belong here.** The platform's — the envelope wrapper, the
empty `details`, `InvalidPayloadError`, `MalformedRequestError`, `NotFoundError` and
`InternalError` — come from `holahost_http.error_schemas`; its middleware's answers
(`401`/`503`, `429`, the transport `413`) are described nowhere per-service, because
restating one fact behind N services makes it N facts that drift.

A service's own error is added in three steps: a `Strict` details model, a `*Body` naming it
with `code: Literal["..."]`, and a place in the `envelope(...)` union its routes declare —
plus the matching row in `errors.py`'s `ERROR_CONTRACT`, which is what decides the status.
"""

from __future__ import annotations

from typing import Annotated, Any

from holahost_http.error_schemas import (
    INTERNAL_RESPONSES,
    InvalidPayloadErrorBody,
    MalformedRequestErrorBody,
    NotFoundErrorBody,
    discriminated,
    envelope,
)

InvalidRequestResponse = envelope(
    "InvalidRequestResponse",
    # `MalformedRequestErrorBody` belongs in every guarded route's 422: `RequestIdMiddleware`
    # answers with it before this service's own validation has anything to say.
    Annotated[InvalidPayloadErrorBody | MalformedRequestErrorBody, discriminated],
)
NotFoundErrorResponse = envelope("NotFoundErrorResponse", NotFoundErrorBody)

DEFAULT_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": NotFoundErrorResponse, "description": "No such resource for this owner."},
    422: {"model": InvalidRequestResponse, "description": "The request could not be accepted."},
    **INTERNAL_RESPONSES,
}
"""What a route declares as `responses=` when it publishes nothing of its own.

A route with its own errors builds its own map instead of extending this one in place: the
statuses a route can answer with are part of what it documents, and one shared mutable map
would put every error on every route."""
