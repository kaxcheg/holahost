from domain.exceptions import DomainValidationError


class TestDomainValidationError:
    def test_carries_message_and_field(self) -> None:
        exc = DomainValidationError("Message text must not be empty", field="messages")
        assert str(exc) == "Message text must not be empty"
        assert exc.field == "messages"

    def test_field_defaults_to_none(self) -> None:
        assert DomainValidationError("bad value").field is None

    def test_is_a_value_error(self) -> None:
        assert isinstance(DomainValidationError("x"), ValueError)
