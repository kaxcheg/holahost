import pytest

from domain.exceptions import DomainValidationError
from domain.value_objects.message import Message
from domain.value_objects.role import Role


class TestMessage:
    def test_holds_role_and_text(self) -> None:
        message = Message(role=Role.USER, text="What time is check-in?")
        assert message.role is Role.USER
        assert message.text == "What time is check-in?"

    def test_keeps_the_text_unchanged(self) -> None:
        assert Message(role=Role.USER, text="  hi\n").text == "  hi\n"

    def test_rejects_empty_text(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            Message(role=Role.USER, text="")
        assert exc.value.field == "messages"

    def test_rejects_whitespace_only_text(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            Message(role=Role.USER, text=" \n\t")
        assert exc.value.field == "messages"
