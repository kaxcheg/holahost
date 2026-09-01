"""The published shape of the platform's own errors, as Pydantic models.

A service declares its error taxonomy twice: once as exception classes (the application
layer, which must not depend on a serialization library) and once as models, which is what
puts the contract into its OpenAPI document. This module holds the half that is the same
for every service — the envelope wrapper, the empty ``details``, and the errors
``holahost-http`` itself defines.

**``message`` is absent from every model here, deliberately.** It is carried on the wire
for a person reading a log or a response by hand, and it is not part of the contract: a
consumer branches on ``code`` and composes what it shows from ``details``. Publishing it
would invite exactly the parsing the contract says not to do.

What is also absent: the platform's *middleware* answers — ``401``/``503`` from
``holahost-auth``, ``429`` and the transport ``413`` from this package. They are identical
behind every service, and restating them in each service's document would make one fact
look like N.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    """Forbids undeclared keys, which is what lets a conformance test fail: a ``details``
    that grew an unpublished key stops validating instead of quietly passing."""

    model_config = ConfigDict(extra="forbid")


class NoDetails(Strict):
    """An error whose identity is the whole message — nothing to parameterise."""


class InvalidPayloadDetails(Strict):
    field: str = Field(description="Which request field failed validation.")
    limit: int | None = Field(description="That field's length limit, or null if it has none.")


class InvalidPayloadErrorBody(Strict):
    code: Literal["InvalidPayloadError"]
    details: InvalidPayloadDetails


class MalformedRequestErrorBody(Strict):
    code: Literal["MalformedRequestError"]
    details: NoDetails


class NotFoundErrorBody(Strict):
    code: Literal["NotFoundError"]
    details: NoDetails


class InternalErrorBody(Strict):
    """The one out-of-contract answer. Anything a service did not publish — an unmapped
    exception, a driver failure, a defect — comes back as exactly this, with an empty
    ``details``: the cause reaches the log, never the caller."""

    # Spelled out rather than `Literal[INTERNAL_ERROR_CODE]`: a `Literal` of a name is
    # not a type to a checker. `tests/test_error_schemas.py` pins the two together.
    code: Literal["InternalError"]
    details: NoDetails


def envelope(name: str, body: Any) -> type[BaseModel]:
    """Wrap one body model (or a discriminated union of them) in ``{"error": ...}``."""
    return type(name, (Strict,), {"__annotations__": {"error": body}})


discriminated = Field(discriminator="code")
"""Tag a union of error bodies by ``code``.

``details`` is a tagged union whose shape depends on which error was thrown, and the
identity is its tag: a consumer switches on ``code``, then reads ``details`` knowing its
keys.
"""

InternalErrorResponse = envelope("InternalErrorResponse", InternalErrorBody)

INTERNAL_RESPONSES: dict[int | str, dict[str, Any]] = {
    500: {"model": InternalErrorResponse, "description": "Out of contract — see the log."}
}
"""Merged into every route's ``responses``. The 500 stays in each service's document
because the service's own handler answers it and a consumer needs the shape; the platform
middleware's answers do not, for the reason in this module's docstring."""

__all__ = [
    "INTERNAL_RESPONSES",
    "InternalErrorBody",
    "InternalErrorResponse",
    "InvalidPayloadDetails",
    "InvalidPayloadErrorBody",
    "MalformedRequestErrorBody",
    "NoDetails",
    "NotFoundErrorBody",
    "Strict",
    "discriminated",
    "envelope",
]
