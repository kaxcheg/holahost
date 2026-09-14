import pytest

from domain.exceptions import DomainValidationError
from domain.value_objects.token_count import TokenCount


class TestTokenCount:
    def test_holds_the_value(self) -> None:
        assert TokenCount(1240).value == 1240

    def test_accepts_zero(self) -> None:
        assert TokenCount(0).value == 0

    def test_rejects_a_negative_value(self) -> None:
        with pytest.raises(DomainValidationError, match="negative") as exc:
            TokenCount(-1)
        assert exc.value.field is None

    def test_is_ordered_by_value(self) -> None:
        assert TokenCount(1) < TokenCount(2)
        assert TokenCount(2) >= TokenCount(2)
