from domain.value_objects.role import Role


class TestRole:
    def test_values_are_the_contract(self) -> None:
        assert [role.value for role in Role] == ["user"]
