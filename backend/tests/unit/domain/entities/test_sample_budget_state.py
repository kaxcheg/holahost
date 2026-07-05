from datetime import date

import pytest

from domain.entities.sample_budget_state import SampleBudgetState

_DAY = date(2024, 1, 15)
_DAY2 = date(2024, 1, 16)


class TestSampleBudgetState:
    def test_create_zeroes_counters(self) -> None:
        state = SampleBudgetState.create(day=_DAY)
        assert state.day == _DAY
        assert state.output_tokens_used == 0
        assert state.dollars_spent_est == 0.0

    def test_from_repo_reconstructs_verbatim(self) -> None:
        state = SampleBudgetState.from_repo(
            day=_DAY, output_tokens_used=5000, dollars_spent_est=0.25
        )
        assert state.day == _DAY
        assert state.output_tokens_used == 5000
        assert state.dollars_spent_est == 0.25

    def test_is_exhausted_false_below_cap(self) -> None:
        state = SampleBudgetState.from_repo(day=_DAY, output_tokens_used=999, dollars_spent_est=0.0)
        assert not state.is_exhausted(cap_tokens=1000)

    def test_is_exhausted_true_at_cap(self) -> None:
        state = SampleBudgetState.from_repo(
            day=_DAY, output_tokens_used=1000, dollars_spent_est=0.0
        )
        assert state.is_exhausted(cap_tokens=1000)

    def test_is_exhausted_true_above_cap(self) -> None:
        state = SampleBudgetState.from_repo(
            day=_DAY, output_tokens_used=1001, dollars_spent_est=0.0
        )
        assert state.is_exhausted(cap_tokens=1000)

    def test_add_usage_accumulates(self) -> None:
        state = SampleBudgetState.create(day=_DAY)
        state.add_usage(output_tokens=300, dollars=0.10)
        assert state.output_tokens_used == 300
        assert state.dollars_spent_est == pytest.approx(0.10)
        state.add_usage(output_tokens=200, dollars=0.05)
        assert state.output_tokens_used == 500
        assert state.dollars_spent_est == pytest.approx(0.15)

    def test_equal_when_same_day_regardless_of_counters(self) -> None:
        a = SampleBudgetState.from_repo(day=_DAY, output_tokens_used=0, dollars_spent_est=0.0)
        b = SampleBudgetState.from_repo(day=_DAY, output_tokens_used=999, dollars_spent_est=9.9)
        assert a == b

    def test_not_equal_when_different_day(self) -> None:
        a = SampleBudgetState.create(day=_DAY)
        b = SampleBudgetState.create(day=_DAY2)
        assert a != b
        not_a_state: object = "not-a-state"
        assert a != not_a_state

    def test_hashable_by_day(self) -> None:
        a = SampleBudgetState.from_repo(day=_DAY, output_tokens_used=0, dollars_spent_est=0.0)
        b = SampleBudgetState.from_repo(day=_DAY, output_tokens_used=500, dollars_spent_est=5.0)
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
