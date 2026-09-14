"""The `Budget` entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from domain.exceptions import DomainValidationError
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from domain.value_objects.provider_name import ProviderName
from domain.value_objects.usage import Usage

BUDGET_WINDOW = timedelta(days=1)


@dataclass(frozen=True, eq=False)
class Budget:
    """What one subject has spent in the current window, against its ceilings.

    Identified by `(scope, key, window_start)`: a client's spend for one day stays the same budget
    as `spent` grows. Nothing stores it — a repository assembles it from the usage log for the
    window and the ceilings from config — and it lives for a single check, hence frozen.

    Exhausted means a counter has reached its ceiling, not that the next call would pass it: the
    check runs before the provider is called and the spend is known only after, so one call may
    overspend.

    :param scope: The dimension the ceilings apply to.
    :param key: The client for both client scopes, the provider for `provider`.
    :param window_start: The window's start, UTC.
    :param spent: What the usage log holds for this subject in the window.
    :param caps: The window's ceilings; both counters positive.
    """

    scope: BudgetScope
    key: ClientId | ProviderName
    window_start: datetime
    spent: Usage
    caps: Usage

    def __post_init__(self) -> None:
        # Assembled from the usage log and config, never from a request — `field` stays None.
        if self.caps.input_tokens.value <= 0 or self.caps.output_tokens.value <= 0:
            raise DomainValidationError("Budget caps must be positive")
        expected = ProviderName if self.scope is BudgetScope.PROVIDER else ClientId
        if not isinstance(self.key, expected):
            raise DomainValidationError(
                f"Budget key for scope {self.scope.value} must be a {expected.__name__}"
            )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Budget):
            return NotImplemented
        return (self.scope, self.key, self.window_start) == (
            other.scope,
            other.key,
            other.window_start,
        )

    def __hash__(self) -> int:
        return hash((self.scope, self.key, self.window_start))

    @property
    def is_exhausted(self) -> bool:
        """Whether either counter has reached its ceiling."""
        return (
            self.spent.input_tokens >= self.caps.input_tokens
            or self.spent.output_tokens >= self.caps.output_tokens
        )

    @property
    def resets_at(self) -> datetime:
        """When the next window starts."""
        return self.window_start + BUDGET_WINDOW
