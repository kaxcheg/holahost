import pytest

from domain.value_objects.email import EMAIL_MAX_LENGTH, Email


class TestEmail:
    def test_valid_email_accepted(self) -> None:
        assert Email("user@example.com").value == "user@example.com"

    def test_rejects_missing_at_sign(self) -> None:
        with pytest.raises(ValueError):
            Email("noatsign.example.com")

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError):
            Email("plainword")

    def test_rejects_too_long(self) -> None:
        with pytest.raises(ValueError):
            Email("a" * EMAIL_MAX_LENGTH + "@example.com")

    def test_rejects_trailing_newline(self) -> None:
        # `$` matches before a trailing `\n`; `\Z` does not (header-injection guard).
        with pytest.raises(ValueError):
            Email("user@example.com\n")
