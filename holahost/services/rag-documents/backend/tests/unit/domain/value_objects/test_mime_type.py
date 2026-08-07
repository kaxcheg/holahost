import pytest

from domain.exceptions import DomainValidationError
from domain.value_objects.mime_type import ALLOWED_MIME_TYPES, MimeType


class TestMimeType:
    def test_accepts_an_allowed_mime_type(self) -> None:
        assert MimeType("application/pdf").value == "application/pdf"

    def test_all_spec_allowed_types_are_accepted(self) -> None:
        for allowed in ALLOWED_MIME_TYPES:
            assert MimeType(allowed).value == allowed

    def test_rejects_a_disallowed_mime_type(self) -> None:
        with pytest.raises(DomainValidationError, match="not supported") as exc:
            MimeType("application/zip")
        assert exc.value.field == "mime_type"
