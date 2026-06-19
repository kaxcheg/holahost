import pytest

from domain.entities.guest_message import MAX_GUEST_MESSAGE_LENGTH, GuestMessage
from domain.exceptions import DomainValidationError


class TestGuestMessage:
    def test_create_sets_text(self) -> None:
        msg = GuestMessage.create("hello guest")
        assert msg.text == "hello guest"

    def test_create_strips_whitespace(self) -> None:
        msg = GuestMessage.create("  hello  ")
        assert msg.text == "hello"

    def test_create_rejects_empty_string(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            GuestMessage.create("")
        assert exc.value.field == "message"
        assert exc.value.reason == "empty"

    def test_create_rejects_whitespace_only(self) -> None:
        with pytest.raises(DomainValidationError, match="empty"):
            GuestMessage.create("   ")

    def test_create_accepts_text_at_exact_max_length(self) -> None:
        text = "a" * MAX_GUEST_MESSAGE_LENGTH
        msg = GuestMessage.create(text)
        assert len(msg.text) == MAX_GUEST_MESSAGE_LENGTH

    def test_create_rejects_text_exceeding_max_length(self) -> None:
        text = "a" * (MAX_GUEST_MESSAGE_LENGTH + 1)
        with pytest.raises(DomainValidationError, match=str(MAX_GUEST_MESSAGE_LENGTH)) as exc:
            GuestMessage.create(text)
        assert exc.value.field == "message"
        assert exc.value.reason == "too_long"

    def test_max_guest_message_length_is_4000(self) -> None:
        assert MAX_GUEST_MESSAGE_LENGTH == 4000

    def test_value_equality(self) -> None:
        a = GuestMessage.create("same text")
        b = GuestMessage.create("same text")
        assert a == b

    def test_inequality_on_different_text(self) -> None:
        a = GuestMessage.create("text A")
        b = GuestMessage.create("text B")
        assert a != b
