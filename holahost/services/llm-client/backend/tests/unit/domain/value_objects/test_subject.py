import pytest

from domain.exceptions import DomainValidationError
from domain.value_objects.subject import Subject


class TestSubject:
    def test_holds_the_value(self) -> None:
        assert Subject("guest-reply-cli").value == "guest-reply-cli"

    def test_equal_by_value(self) -> None:
        assert Subject("user-42") == Subject("user-42")

    def test_rejects_an_empty_value(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            Subject("")
        assert exc.value.field is None

    def test_rejects_a_blank_value(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            Subject("   ")
        assert exc.value.field is None
