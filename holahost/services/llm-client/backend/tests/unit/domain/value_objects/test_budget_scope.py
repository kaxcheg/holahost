from domain.value_objects.budget_scope import BudgetScope


class TestBudgetScope:
    def test_values_are_the_contract(self) -> None:
        assert [scope.value for scope in BudgetScope] == [
            "client",
            "client_downgrade",
            "provider",
        ]
