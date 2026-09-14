import dataclasses

import pytest

from domain.value_objects.token_count import TokenCount
from domain.value_objects.usage import Usage


class TestUsage:
    def test_holds_input_and_output_separately(self) -> None:
        usage = Usage(input_tokens=TokenCount(1240), output_tokens=TokenCount(310))
        assert usage.input_tokens == TokenCount(1240)
        assert usage.output_tokens == TokenCount(310)

    def test_equal_by_value(self) -> None:
        assert Usage(TokenCount(1), TokenCount(2)) == Usage(TokenCount(1), TokenCount(2))
        assert Usage(TokenCount(1), TokenCount(2)) != Usage(TokenCount(2), TokenCount(1))

    def test_is_immutable(self) -> None:
        usage = Usage(input_tokens=TokenCount(1), output_tokens=TokenCount(2))
        with pytest.raises(dataclasses.FrozenInstanceError):
            usage.input_tokens = TokenCount(5)  # type: ignore[misc]
