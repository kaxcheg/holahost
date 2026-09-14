import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from domain.entities.budget import Budget
from domain.exceptions import DomainValidationError
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from domain.value_objects.provider_name import ProviderName
from domain.value_objects.token_count import TokenCount
from domain.value_objects.usage import Usage

_WINDOW = datetime(2026, 9, 13, tzinfo=UTC)
_CLIENT = ClientId("guest-reply-cli")


def _usage(input_tokens: int, output_tokens: int) -> Usage:
    return Usage(input_tokens=TokenCount(input_tokens), output_tokens=TokenCount(output_tokens))


def _budget(
    *,
    scope: BudgetScope = BudgetScope.CLIENT,
    key: ClientId | ProviderName = _CLIENT,
    window_start: datetime = _WINDOW,
    spent: Usage | None = None,
    caps: Usage | None = None,
) -> Budget:
    return Budget(
        scope=scope,
        key=key,
        window_start=window_start,
        spent=spent if spent is not None else _usage(0, 0),
        caps=caps if caps is not None else _usage(100, 10),
    )


class TestBudget:
    def test_holds_fields(self) -> None:
        budget = _budget(spent=_usage(40, 4))
        assert budget.scope is BudgetScope.CLIENT
        assert budget.key == _CLIENT
        assert budget.window_start == _WINDOW
        assert budget.spent == _usage(40, 4)
        assert budget.caps == _usage(100, 10)

    def test_rejects_a_zero_input_cap(self) -> None:
        with pytest.raises(DomainValidationError, match="caps") as exc:
            _budget(caps=_usage(0, 10))
        assert exc.value.field is None

    def test_rejects_a_zero_output_cap(self) -> None:
        with pytest.raises(DomainValidationError, match="caps") as exc:
            _budget(caps=_usage(100, 0))
        assert exc.value.field is None

    def test_rejects_a_provider_key_for_a_client_scope(self) -> None:
        with pytest.raises(DomainValidationError, match="key") as exc:
            _budget(scope=BudgetScope.CLIENT, key=ProviderName("anthropic"))
        assert exc.value.field is None

    def test_rejects_a_client_key_for_the_provider_scope(self) -> None:
        with pytest.raises(DomainValidationError, match="key") as exc:
            _budget(scope=BudgetScope.PROVIDER, key=_CLIENT)
        assert exc.value.field is None

    def test_rejects_a_provider_key_for_the_downgrade_pool(self) -> None:
        with pytest.raises(DomainValidationError, match="key") as exc:
            _budget(scope=BudgetScope.CLIENT_DOWNGRADE, key=ProviderName("anthropic"))
        assert exc.value.field is None

    def test_accepts_a_client_key_for_the_downgrade_pool(self) -> None:
        assert _budget(scope=BudgetScope.CLIENT_DOWNGRADE).key == _CLIENT

    def test_accepts_a_provider_key_for_the_provider_scope(self) -> None:
        budget = _budget(scope=BudgetScope.PROVIDER, key=ProviderName("anthropic"))
        assert budget.key == ProviderName("anthropic")

    def test_not_exhausted_below_both_caps(self) -> None:
        assert _budget(spent=_usage(99, 9)).is_exhausted is False

    def test_exhausted_when_input_reaches_its_cap(self) -> None:
        assert _budget(spent=_usage(100, 0)).is_exhausted is True

    def test_exhausted_when_output_reaches_its_cap(self) -> None:
        assert _budget(spent=_usage(0, 10)).is_exhausted is True

    def test_exhausted_past_its_cap(self) -> None:
        assert _budget(spent=_usage(150, 0)).is_exhausted is True

    def test_resets_a_day_after_the_window_starts(self) -> None:
        assert _budget().resets_at == _WINDOW + timedelta(days=1)

    def test_is_immutable(self) -> None:
        budget = _budget()
        with pytest.raises(dataclasses.FrozenInstanceError):
            budget.spent = _usage(1, 1)  # type: ignore[misc]

    def test_equal_when_same_scope_key_and_window_regardless_of_spend(self) -> None:
        assert _budget(spent=_usage(1, 1)) == _budget(spent=_usage(50, 5), caps=_usage(200, 20))

    def test_not_equal_across_scopes_keys_windows_or_types(self) -> None:
        assert _budget() != _budget(scope=BudgetScope.CLIENT_DOWNGRADE)
        assert _budget() != _budget(key=ClientId("other-client"))
        assert _budget() != _budget(window_start=_WINDOW + timedelta(days=1))
        assert _budget() != object()

    def test_hashable_by_identity(self) -> None:
        a = _budget(spent=_usage(1, 1))
        b = _budget(spent=_usage(2, 2))
        assert hash(a) == hash(b)
        assert len({a, b}) == 1

    def test_budgets_of_different_clients_stay_apart_in_a_set(self) -> None:
        assert len({_budget(), _budget(key=ClientId("other-client"))}) == 2
