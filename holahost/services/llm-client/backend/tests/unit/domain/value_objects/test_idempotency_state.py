from domain.value_objects.idempotency_state import IdempotencyState


class TestIdempotencyState:
    def test_values_are_the_contract(self) -> None:
        assert [state.value for state in IdempotencyState] == ["in_flight", "completed"]
