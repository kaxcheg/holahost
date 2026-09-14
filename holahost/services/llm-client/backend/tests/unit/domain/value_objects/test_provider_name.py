import pytest

from domain.exceptions import DomainValidationError
from domain.value_objects.provider_name import ProviderName


class TestProviderName:
    def test_holds_the_value(self) -> None:
        assert ProviderName("anthropic").value == "anthropic"

    def test_equal_by_value(self) -> None:
        assert ProviderName("anthropic") == ProviderName("anthropic")

    def test_rejects_an_empty_value(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            ProviderName("")
        assert exc.value.field is None

    def test_rejects_a_blank_value(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            ProviderName("   ")
        assert exc.value.field is None
