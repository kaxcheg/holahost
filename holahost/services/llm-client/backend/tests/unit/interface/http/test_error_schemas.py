"""The two declarations of one error contract must agree.

`application/exceptions` declares each error — its identity (class name) and its `details`
(`details_dict()`); `interface/http/error_schemas` declares the same as Pydantic models, which is
what puts it into `docs/openapi.json`. The layering forbids merging them, so this file is what
stops them drifting: rename an error class, add a `details` key, or change one without the other,
and one of these fails.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from holahost_http import (
    InvalidPayloadError,
    MalformedRequestError,
    RateLimitExceededError,
    error_envelope,
)
from holahost_http.error_schemas import (
    InvalidPayloadErrorBody,
    MalformedRequestErrorBody,
    RateLimitExceededErrorBody,
)
from holahost_http.errors import PlatformError
from pydantic import BaseModel

from application.exceptions import (
    BudgetExhaustedError,
    ContentRefusedError,
    ContextOverflowError,
    DuplicateRequestError,
    RequestTooSlowForSyncError,
    UnknownModelError,
    UpstreamLlmError,
)
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.idempotency_state import IdempotencyState
from interface.http.error_schemas import (
    BudgetExhaustedErrorBody,
    ContentRefusedErrorBody,
    ContextOverflowErrorBody,
    DuplicateRequestErrorBody,
    RequestTooSlowForSyncErrorBody,
    UnknownModelErrorBody,
    UpstreamLlmErrorBody,
)
from interface.http.errors import ERROR_CONTRACT

# One sample per published error, paired with the model that publishes it. Both nullable
# values — `limit` and `upstream_status` — appear once as null: `None` is a published value.
_PUBLISHED: list[tuple[PlatformError, type[BaseModel]]] = [
    (InvalidPayloadError(field="messages"), InvalidPayloadErrorBody),
    (InvalidPayloadError(field="idempotency_key", limit=128), InvalidPayloadErrorBody),
    (MalformedRequestError(), MalformedRequestErrorBody),
    # The limiter's, published beside the budget's because both answer this route's 429.
    (RateLimitExceededError(retry_after=30), RateLimitExceededErrorBody),
    (UnknownModelError(requested="huge", available_aliases=["fast"]), UnknownModelErrorBody),
    (ContextOverflowError(max_context=200_000, estimated=210_016), ContextOverflowErrorBody),
    (
        RequestTooSlowForSyncError(max_tokens_allowed=500, budget_seconds=20.0),
        RequestTooSlowForSyncErrorBody,
    ),
    (DuplicateRequestError(state=IdempotencyState.COMPLETED), DuplicateRequestErrorBody),
    (
        BudgetExhaustedError(scope=BudgetScope.CLIENT, resets_at=datetime(2026, 9, 29, tzinfo=UTC)),
        BudgetExhaustedErrorBody,
    ),
    (
        ContentRefusedError(provider="anthropic", model="m", input_tokens=4, output_tokens=0),
        ContentRefusedErrorBody,
    ),
    (UpstreamLlmError(attempts=2, upstream_status=529, provider_timeouts=0), UpstreamLlmErrorBody),
    (UpstreamLlmError(attempts=1, upstream_status=None, provider_timeouts=1), UpstreamLlmErrorBody),
]


@pytest.mark.parametrize(("error", "model"), _PUBLISHED, ids=lambda x: getattr(x, "__name__", ""))
class TestEachPublishedErrorMatchesItsModel:
    def test_the_published_half_of_the_envelope_validates(
        self, error: PlatformError, model: type[BaseModel]
    ) -> None:
        # `message` is dropped first, and that is the assertion: it rides the wire for a person
        # and is in no model, so `extra="forbid"` rejects it. Everything else must validate.
        envelope = error_envelope(error.code, str(error), error.details_dict())
        body = dict(envelope["error"])  # type: ignore[call-overload]
        assert body.pop("message")

        model.model_validate(body)

    def test_the_identity_matches(self, error: PlatformError, model: type[BaseModel]) -> None:
        published = model.model_fields["code"].annotation
        assert published is not None
        assert error.code in getattr(published, "__args__", ())


def test_every_error_in_the_contract_has_a_model() -> None:
    covered = {type(error) for error, _ in _PUBLISHED}
    assert set(ERROR_CONTRACT) <= covered
