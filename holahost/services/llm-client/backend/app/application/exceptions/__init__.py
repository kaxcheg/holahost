"""The errors this service throws at its boundary — one class per error.

Each class is the whole contract for the error it names: its **identity** on the wire is
its class name, verbatim (`PlatformError.code`), and the shape of its **`details`** is what
`details_dict()` returns. Nothing else is contractual — the `message` is for a person
reading a log, and the HTTP status is a projection applied by `interface/http/errors.py`,
which is why two errors may share one status and why changing a status is not a change to
this file.

No two errors share an identity: a consumer builds its message from `details`, so what the
identity has to name is which error the service threw, not the category it falls in.

Three of the errors below are re-exported rather than declared: every service rejects a
field, refuses a request that broke the transport contract, and answers for a resource that
is absent or another subject's — with the same identity and the same `details` each time.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from holahost_http import (
    InvalidPayloadError,
    MalformedRequestError,
    NotFoundError,
    PlatformError,
)

from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.idempotency_state import IdempotencyState

__all__ = [
    "ApplicationError",
    "BudgetExhaustedError",
    "ContentRefusedError",
    "ContextOverflowError",
    "DuplicateRequestError",
    "InvalidPayloadError",
    "MalformedRequestError",
    "NotFoundError",
    "RequestTooSlowForSyncError",
    "UnknownModelError",
    "UpstreamLlmError",
    "UsageNotRecordedError",
]


class ApplicationError(PlatformError):
    """Base for every application-layer, HTTP-facing exception of this service.

    Inherits the platform base for the envelope contract it defines (`code` +
    `details_dict()`); the errors below stay this service's own.

    Never thrown itself, and deliberately absent from the interface layer's status table:
    an instance of the base, or of a subclass nobody published, is by construction not one
    of this service's errors and is answered `500 InternalError` with an empty body.
    """


class UnknownModelError(ApplicationError):
    """Nothing in the registry answers the requested alias or model identifier.

    Also what an alias answers when every model it points at belongs to a disabled provider: to the
    caller the two are the same fact, and `available_aliases` is the remedy for both.
    """

    def __init__(self, *, requested: str, available_aliases: list[str]) -> None:
        super().__init__("unknown model")
        self.requested = requested
        self.available_aliases = available_aliases

    def details_dict(self) -> Mapping[str, object]:
        return {"requested": self.requested, "available_aliases": list(self.available_aliases)}


class ContextOverflowError(ApplicationError):
    """The input estimate plus `max_tokens` exceeds the model's context window.

    `estimated` is that sum. The estimate is an upper bound, so a request near the limit may be
    refused although it would fit; the remedy is a shorter input or a smaller `max_tokens`.
    """

    def __init__(self, *, max_context: int, estimated: int) -> None:
        super().__init__("context overflow")
        self.max_context = max_context
        self.estimated = estimated

    def details_dict(self) -> Mapping[str, object]:
        return {"max_context": self.max_context, "estimated": self.estimated}


class RequestTooSlowForSyncError(ApplicationError):
    """A full-length answer would not finish in the time left to the request.

    Refused before any provider is paid for an answer the gateway would cut off.
    `max_tokens_allowed` is the largest value that would have fitted into `budget_seconds`.
    """

    def __init__(self, *, max_tokens_allowed: int, budget_seconds: float) -> None:
        super().__init__("request too slow for the synchronous mode")
        self.max_tokens_allowed = max_tokens_allowed
        self.budget_seconds = budget_seconds

    def details_dict(self) -> Mapping[str, object]:
        return {
            "max_tokens_allowed": self.max_tokens_allowed,
            "budget_seconds": self.budget_seconds,
        }


class DuplicateRequestError(ApplicationError):
    """A request with the same `Idempotency-Key` is in flight or already completed.

    The first answer's text is kept nowhere, so a repeat learns only the state — it is protected
    from paying twice, not handed the result.
    """

    def __init__(self, *, state: IdempotencyState) -> None:
        super().__init__("duplicate request")
        self.state = state

    def details_dict(self) -> Mapping[str, object]:
        return {"state": self.state.value}


class BudgetExhaustedError(ApplicationError):
    """A spend ceiling is exhausted and the request cannot be served.

    `scope` names the ceiling. `resets_at` is also kept as a `datetime`, because the response's
    `Retry-After` is computed from it where the response is written.
    """

    def __init__(self, *, scope: BudgetScope, resets_at: datetime) -> None:
        super().__init__("budget exhausted")
        self.scope = scope
        self.resets_at = resets_at

    def details_dict(self) -> Mapping[str, object]:
        return {"scope": self.scope.value, "resets_at": self.resets_at.isoformat()}


class UpstreamLlmError(ApplicationError):
    """Every candidate model failed transiently, or the time ran out between failures. Retryable.

    `upstream_status` is the vendor status of the last transient failure — `None` when it was a
    timeout. `provider_timeouts` counts the attempts cut off by the service's own timeout; it feeds
    the completion event, not `details`.
    """

    def __init__(
        self, *, attempts: int, upstream_status: int | None, provider_timeouts: int
    ) -> None:
        super().__init__("upstream LLM failure")
        self.attempts = attempts
        self.upstream_status = upstream_status
        self.provider_timeouts = provider_timeouts

    def details_dict(self) -> Mapping[str, object]:
        return {"attempts": self.attempts, "upstream_status": self.upstream_status}


class ContentRefusedError(ApplicationError):
    """The model declined to answer this content.

    The call was paid for and recorded; the same content will be refused again. `provider` and
    `model` name the one that refused — after a downgrade or failover it is not the one asked for.
    """

    def __init__(self, *, provider: str, model: str) -> None:
        super().__init__("content refused")
        self.provider = provider
        self.model = model

    def details_dict(self) -> Mapping[str, object]:
        return {"provider": self.provider, "model": self.model}


class UsageNotRecordedError(ApplicationError):
    """A paid call's usage record could not be written.

    Published by no contract, so it is answered `500` — but it carries the spend the provider
    confirmed, so the completion event can still report what was charged: once the write has failed
    this is the only place the figures survive. Raised from the storage failure, which stays its
    cause and is named in the message: those failures carry no message of their own, and without
    the name a defect would read in the log the same as an outage.
    """

    def __init__(
        self, *, input_tokens: int, output_tokens: int, provider: str, model: str, cause: Exception
    ) -> None:
        super().__init__(f"usage not recorded: {type(cause).__name__}")
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.provider = provider
        self.model = model
