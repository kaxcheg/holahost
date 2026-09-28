"""The published shape of every error this service can answer with.

`application/exceptions` declares the errors themselves; this module is the same contract as
Pydantic models, which is what puts it into `docs/openapi.json` — the artifact a consumer
integrates against, diffed in CI by `make openapi-check`, so a changed `details` key becomes
a schema change someone has to approve.

Two declarations of one contract, paid deliberately: the application layer must not depend
on a serialization library. `tests/unit/interface/http/test_error_schemas.py` closes the gap by
validating every published error against its own model.

The unions are discriminated on `code`: `details` is a tagged union whose shape depends on
the error, and the identity is its tag. A consumer switches on `code`, then reads `details`
knowing its keys. `message` is in no model — it rides the wire for a person reading a log by
hand, and publishing it would invite parsing it.

**Only this service's own errors belong here.** The platform's — the envelope wrapper, the
empty `details`, `InvalidPayloadError`, `MalformedRequestError`, `RateLimitExceededError` and
`InternalError` — come from `holahost_http.error_schemas`; its middleware's answers (`401`/`503`,
the transport `413`) are described nowhere per-service, because restating one fact behind N
services makes it N facts that drift. The limiter's `429` is the exception: it shares a status with
the budget's, so the route's `429` union has to name both.

A service's own error is added in three steps: a `Strict` details model, a `*Body` naming it
with `code: Literal["..."]`, and a place in the response its routes declare — plus the matching
row in `errors.py`'s `ERROR_CONTRACT`, which is what decides the status.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from holahost_http.error_schemas import (
    INTERNAL_RESPONSES,
    InvalidPayloadErrorBody,
    MalformedRequestErrorBody,
    RateLimitExceededErrorBody,
    Strict,
    discriminated,
    envelope,
)
from pydantic import Field


class UnknownModelDetails(Strict):
    requested: str = Field(description="The alias or model id the request named.")
    available_aliases: list[str] = Field(description="The aliases this service resolves.")


class ContextOverflowDetails(Strict):
    max_context: int = Field(description="The model's context window, in tokens.")
    estimated: int = Field(description="The input's upper-bound estimate plus `max_tokens`.")


class RequestTooSlowForSyncDetails(Strict):
    max_tokens_allowed: int = Field(description="The largest `max_tokens` one attempt can finish.")
    budget_seconds: float = Field(description="The time that `max_tokens_allowed` was fitted to.")


class DuplicateRequestDetails(Strict):
    state: Literal["in_flight", "completed"] = Field(
        description="Where the request that holds the key is; its answer is not returned again."
    )


class BudgetExhaustedDetails(Strict):
    scope: Literal["client", "client_downgrade", "provider"] = Field(
        description="The ceiling that ran out: the caller's own, its downgrade pool, a provider's."
    )
    resets_at: datetime = Field(description="When the next budget window starts (UTC).")


class ContentRefusedDetails(Strict):
    provider: str = Field(description="The provider whose model refused.")
    model: str = Field(description="The model that refused — not always the one asked for.")


class UpstreamLlmDetails(Strict):
    attempts: int = Field(description="Provider calls made, across every candidate.")
    upstream_status: int | None = Field(
        description="The last transient failure's vendor status; null for a timeout."
    )


# Each model names the error it publishes in a comment, not a docstring: a docstring becomes the
# schema's `description` in the generated document, and where the original is declared is a fact
# about this repository, not about the API.
#
# `application.exceptions.UnknownModelError`.
class UnknownModelErrorBody(Strict):
    code: Literal["UnknownModelError"]
    details: UnknownModelDetails


# `application.exceptions.ContextOverflowError`.
class ContextOverflowErrorBody(Strict):
    code: Literal["ContextOverflowError"]
    details: ContextOverflowDetails


# `application.exceptions.RequestTooSlowForSyncError`.
class RequestTooSlowForSyncErrorBody(Strict):
    code: Literal["RequestTooSlowForSyncError"]
    details: RequestTooSlowForSyncDetails


# `application.exceptions.DuplicateRequestError`.
class DuplicateRequestErrorBody(Strict):
    code: Literal["DuplicateRequestError"]
    details: DuplicateRequestDetails


# `application.exceptions.BudgetExhaustedError`.
class BudgetExhaustedErrorBody(Strict):
    code: Literal["BudgetExhaustedError"]
    details: BudgetExhaustedDetails


# `application.exceptions.ContentRefusedError`.
class ContentRefusedErrorBody(Strict):
    code: Literal["ContentRefusedError"]
    details: ContentRefusedDetails


# `application.exceptions.UpstreamLlmError`.
class UpstreamLlmErrorBody(Strict):
    code: Literal["UpstreamLlmError"]
    details: UpstreamLlmDetails


GenerateRejectedResponse = envelope(
    "GenerateRejectedResponse",
    Annotated[
        # `MalformedRequestErrorBody` belongs in every guarded route's 422: `RequestIdMiddleware`
        # answers with it before this service's own validation has anything to say.
        InvalidPayloadErrorBody
        | MalformedRequestErrorBody
        | ContextOverflowErrorBody
        | RequestTooSlowForSyncErrorBody
        | ContentRefusedErrorBody,
        discriminated,
    ],
)
UnknownModelErrorResponse = envelope("UnknownModelErrorResponse", UnknownModelErrorBody)
DuplicateRequestErrorResponse = envelope("DuplicateRequestErrorResponse", DuplicateRequestErrorBody)
GenerateTooManyResponse = envelope(
    "GenerateTooManyResponse",
    Annotated[
        # The rate limiter's body is the platform's, yet it answers this route's 429 too: a union
        # without it would tell a consumer every 429 here is the budget.
        BudgetExhaustedErrorBody | RateLimitExceededErrorBody,
        discriminated,
    ],
)
UpstreamLlmErrorResponse = envelope("UpstreamLlmErrorResponse", UpstreamLlmErrorBody)

GENERATE_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": UnknownModelErrorResponse, "description": "No model answers this name."},
    409: {"model": DuplicateRequestErrorResponse, "description": "The key is already in use."},
    422: {"model": GenerateRejectedResponse, "description": "The request could not be served."},
    429: {
        "model": GenerateTooManyResponse,
        "description": (
            "`BudgetExhaustedError`: a spend ceiling is exhausted until `details.resets_at`. "
            "`RateLimitExceededError`: too many requests in the rate-limit window."
        ),
        "headers": {
            "Retry-After": {
                "description": "Seconds to wait — until the budget window resets, or the limit's.",
                "schema": {"type": "integer", "minimum": 1},
            }
        },
    },
    502: {
        "model": UpstreamLlmErrorResponse,
        "description": "Every candidate model failed transiently. Retryable.",
    },
    **INTERNAL_RESPONSES,
}
"""`POST /generate`. The platform's other edge answers — `401`, the transport `413` — are not
restated; the limiter's `429` is, only because it shares a status with the budget's."""
