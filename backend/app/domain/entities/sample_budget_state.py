from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(eq=False)
class SampleBudgetState:
    """Borderline-persistent entity tracking daily sample-flow token budget (spec §7.8).

    Identified by ``day``; two instances for the same day are considered equal regardless
    of their counters. Persisted in the ``sample_budget`` table (§4.5).

    Args:
        day: UTC calendar date this budget row covers.
        output_tokens_used: Cumulative output tokens consumed today.
        dollars_spent_est: Estimated cumulative cost today (USD).
    """

    day: date
    output_tokens_used: int
    dollars_spent_est: float

    @classmethod
    def create(cls, day: date) -> SampleBudgetState:
        """Create a fresh budget row for a given day with zero counters.

        Args:
            day: The UTC calendar date.

        Returns:
            A new SampleBudgetState with zeroed counters.
        """
        return cls(day=day, output_tokens_used=0, dollars_spent_est=0.0)

    @classmethod
    def from_repo(
        cls,
        day: date,
        output_tokens_used: int,
        dollars_spent_est: float,
    ) -> SampleBudgetState:
        """Reconstruct a SampleBudgetState from a persistence row.

        Args:
            day: The UTC calendar date.
            output_tokens_used: Stored token counter.
            dollars_spent_est: Stored cost estimate.

        Returns:
            A SampleBudgetState reflecting the persisted values.
        """
        return cls(
            day=day, output_tokens_used=output_tokens_used, dollars_spent_est=dollars_spent_est
        )

    def is_exhausted(self, cap_tokens: int) -> bool:
        """Check whether the daily token budget is exhausted.

        Args:
            cap_tokens: Daily token cap from Settings (SAMPLE_BUDGET_DAILY_CAP).

        Returns:
            True if output_tokens_used >= cap_tokens.
        """
        return self.output_tokens_used >= cap_tokens

    def add_usage(self, output_tokens: int, dollars: float) -> None:
        """Accumulate token and cost usage after a successful sample generation.

        Args:
            output_tokens: Output tokens produced by this call.
            dollars: Estimated cost for this call.
        """
        self.output_tokens_used += output_tokens
        self.dollars_spent_est += dollars

    def __eq__(self, other: object) -> bool:
        """Equality by ``day`` (persistent-entity identity)."""
        if not isinstance(other, SampleBudgetState):
            return NotImplemented
        return self.day == other.day

    def __hash__(self) -> int:
        """Hash by ``day`` (stable under mutation)."""
        return hash(self.day)
