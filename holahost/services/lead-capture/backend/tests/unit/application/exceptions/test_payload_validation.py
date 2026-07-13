from __future__ import annotations

import pytest

from application.exceptions import (
    InvalidMagicLinkError,
    InvalidPayloadError,
    magic_link_validation,
    payload_validation,
)
from domain.exceptions import DomainValidationError


class TestPayloadValidation:
    def test_passes_through_without_error(self) -> None:
        with payload_validation():
            x = 1
        assert x == 1

    def test_wraps_domain_validation_into_invalid_payload(self) -> None:
        with pytest.raises(InvalidPayloadError) as exc, payload_validation():
            raise DomainValidationError("Email: invalid format")
        assert "Email: invalid format" in str(exc.value)
        assert exc.value.code == "ERR_INVALID_PAYLOAD"
        assert isinstance(exc.value.__cause__, DomainValidationError)

    def test_plain_value_error_propagates_unwrapped(self) -> None:
        # Narrowed to DomainValidationError only: a bare ValueError is an unconverted internal
        # bug (→ 500), not a masked client 422, so it must escape untouched.
        with pytest.raises(ValueError) as exc, payload_validation():
            raise ValueError("not a domain error")
        assert not isinstance(exc.value, InvalidPayloadError)

    def test_does_not_wrap_non_value_error(self) -> None:
        with pytest.raises(KeyError), payload_validation():
            raise KeyError("nope")

    def test_propagates_domain_validation_field_and_reason(self) -> None:
        with pytest.raises(InvalidPayloadError) as exc, payload_validation():
            raise DomainValidationError("bad name", field="name", reason="empty")
        assert exc.value.field == "name"
        assert exc.value.reason == "empty"
        assert "bad name" in str(exc.value)


class TestMagicLinkValidation:
    def test_passes_through_without_error(self) -> None:
        with magic_link_validation():
            x = 1
        assert x == 1

    def test_wraps_value_error_into_invalid_magic_link(self) -> None:
        with pytest.raises(InvalidMagicLinkError) as exc, magic_link_validation():
            raise ValueError("MagicLink: empty value")
        assert exc.value.code == "ERR_INVALID_MAGIC_LINK"
        assert isinstance(exc.value.__cause__, ValueError)

    def test_does_not_wrap_non_value_error(self) -> None:
        with pytest.raises(KeyError), magic_link_validation():
            raise KeyError("nope")
