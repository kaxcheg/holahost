from domain.exceptions import DomainValidationError


class TestDomainValidationError:
    def test_carries_message_and_field(self) -> None:
        exc = DomainValidationError("Name must not be empty", field="name")
        assert str(exc) == "Name must not be empty"
        assert exc.field == "name"

    def test_field_defaults_to_none(self) -> None:
        assert DomainValidationError("bad value").field is None

    def test_is_a_value_error(self) -> None:
        assert isinstance(DomainValidationError("x"), ValueError)
