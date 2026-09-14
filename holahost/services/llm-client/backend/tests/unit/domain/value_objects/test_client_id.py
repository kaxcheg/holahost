import pytest

from domain.exceptions import DomainValidationError
from domain.value_objects.client_id import ClientId


class TestClientId:
    def test_holds_the_value(self) -> None:
        assert ClientId("guest-reply-cli").value == "guest-reply-cli"

    def test_equal_by_value(self) -> None:
        assert ClientId("guest-reply-cli") == ClientId("guest-reply-cli")

    def test_rejects_an_empty_value(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            ClientId("")
        assert exc.value.field is None

    def test_rejects_a_blank_value(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            ClientId("   ")
        assert exc.value.field is None
