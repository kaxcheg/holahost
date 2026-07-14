import pytest
from pydantic import SecretStr

from domain.exceptions import DomainValidationError
from domain.value_objects.magic_link import MagicLink


class TestMagicLink:
    def test_wraps_and_exposes_secret(self) -> None:
        ml = MagicLink(SecretStr("tok-123"))
        assert ml.value.get_secret_value() == "tok-123"

    def test_repr_does_not_leak_secret(self) -> None:
        assert "super-secret" not in repr(MagicLink(SecretStr("super-secret")))

    def test_equality_by_value(self) -> None:
        assert MagicLink(SecretStr("x")) == MagicLink(SecretStr("x"))

    def test_empty_secret_rejected(self) -> None:
        # Empty/invalid token is a 401 (use case maps to InvalidMagicLinkError), not a 422 payload
        # field → plain ValueError, never DomainValidationError.
        with pytest.raises(ValueError) as exc:
            MagicLink(SecretStr(""))
        assert not isinstance(exc.value, DomainValidationError)
