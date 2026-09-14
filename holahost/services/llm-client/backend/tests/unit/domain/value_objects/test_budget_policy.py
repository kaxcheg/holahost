from domain.value_objects.budget_policy import BudgetPolicy


class TestBudgetPolicy:
    def test_values_are_the_contract(self) -> None:
        assert [policy.value for policy in BudgetPolicy] == ["reject", "downgrade"]
