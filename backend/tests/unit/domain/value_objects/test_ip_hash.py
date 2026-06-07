import pytest

from domain.value_objects.ip_hash import IpHash


class TestIpHash:
    def test_valid_64_lowercase_hex_accepted(self) -> None:
        value = "0123456789abcdef" * 4
        assert IpHash(value).value == value

    def test_rejects_wrong_length(self) -> None:
        with pytest.raises(ValueError):
            IpHash("abc")

    def test_rejects_uppercase(self) -> None:
        with pytest.raises(ValueError):
            IpHash("A" * 64)

    def test_rejects_non_hex(self) -> None:
        with pytest.raises(ValueError):
            IpHash("g" * 64)

    def test_rejects_trailing_newline(self) -> None:
        # `$` matches before a trailing `\n`; `\Z` does not.
        with pytest.raises(ValueError):
            IpHash("0123456789abcdef" * 4 + "\n")
