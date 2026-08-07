import pytest

from domain.value_objects.owner_subject import OwnerSubject


class TestOwnerSubject:
    def test_accepts_a_nonempty_value(self) -> None:
        assert OwnerSubject("user-123").value == "user-123"

    def test_strips_surrounding_whitespace_before_checking(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            OwnerSubject("   ")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            OwnerSubject("")

    def test_equality_is_exact_value_match(self) -> None:
        assert OwnerSubject("user-123") == OwnerSubject("user-123")
        assert OwnerSubject("user-123") != OwnerSubject("user-456")
