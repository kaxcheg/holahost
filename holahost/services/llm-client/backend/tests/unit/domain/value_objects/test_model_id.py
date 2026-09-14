import pytest

from domain.exceptions import DomainValidationError
from domain.value_objects.model_id import ModelId


class TestModelId:
    def test_holds_the_value(self) -> None:
        assert ModelId("claude-haiku-4-5").value == "claude-haiku-4-5"

    def test_equal_by_value(self) -> None:
        assert ModelId("claude-haiku-4-5") == ModelId("claude-haiku-4-5")

    def test_rejects_an_empty_value(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            ModelId("")
        assert exc.value.field is None

    def test_rejects_a_blank_value(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            ModelId("   ")
        assert exc.value.field is None
