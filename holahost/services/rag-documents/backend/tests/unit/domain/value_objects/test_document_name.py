import pytest

from domain.exceptions import DomainValidationError
from domain.value_objects.document_name import MAX_DOCUMENT_NAME_LENGTH, DocumentName


class TestDocumentName:
    def test_accepts_a_valid_name(self) -> None:
        assert DocumentName("Guidebook.pdf").value == "Guidebook.pdf"

    def test_strips_surrounding_whitespace(self) -> None:
        assert DocumentName("  Guidebook.pdf  ").value == "Guidebook.pdf"

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(DomainValidationError, match="empty") as exc:
            DocumentName("   ")
        assert exc.value.field == "name"

    def test_rejects_name_longer_than_max_length(self) -> None:
        too_long = "a" * (MAX_DOCUMENT_NAME_LENGTH + 1)
        with pytest.raises(DomainValidationError, match="length") as exc:
            DocumentName(too_long)
        assert exc.value.field == "name"

    def test_accepts_name_at_exactly_max_length(self) -> None:
        exactly = "a" * MAX_DOCUMENT_NAME_LENGTH
        assert DocumentName(exactly).value == exactly

    def test_rejects_control_characters(self) -> None:
        with pytest.raises(DomainValidationError, match="control") as exc:
            DocumentName("bad\x00name")
        assert exc.value.field == "name"
