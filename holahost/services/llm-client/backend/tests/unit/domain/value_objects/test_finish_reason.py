from domain.value_objects.finish_reason import FinishReason


class TestFinishReason:
    def test_values_are_the_contract(self) -> None:
        assert [reason.value for reason in FinishReason] == ["stop", "max_tokens"]
