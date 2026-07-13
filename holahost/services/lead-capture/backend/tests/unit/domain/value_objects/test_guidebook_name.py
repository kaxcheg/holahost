import pytest

from domain.value_objects.guidebook_name import GUIDEBOOK_NAME_MAX_LENGTH, GuidebookName


class TestGuidebookName:
    def test_valid_name_accepted(self) -> None:
        assert GuidebookName("Riverside Loft").value == "Riverside Loft"

    def test_equality_by_value(self) -> None:
        assert GuidebookName("A") == GuidebookName("A")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            GuidebookName("")

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(ValueError):
            GuidebookName("   ")

    def test_accepts_max_length(self) -> None:
        value = "x" * GUIDEBOOK_NAME_MAX_LENGTH
        assert GuidebookName(value).value == value

    def test_rejects_too_long(self) -> None:
        # §10.6 property_name max_length=100 mirrored into the backend (D6).
        with pytest.raises(ValueError):
            GuidebookName("x" * (GUIDEBOOK_NAME_MAX_LENGTH + 1))
