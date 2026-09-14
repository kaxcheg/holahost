"""The state of a request holding an idempotency key."""

from __future__ import annotations

from enum import StrEnum


class IdempotencyState(StrEnum):
    """Where the request holding an idempotency key is — what a duplicate is told."""

    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
