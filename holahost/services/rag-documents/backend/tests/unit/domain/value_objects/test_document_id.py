import uuid

import pytest

from domain.value_objects.document_id import DocumentId


class TestDocumentId:
    def test_new_generates_a_valid_uuid(self) -> None:
        doc_id = DocumentId.new()
        assert isinstance(doc_id, uuid.UUID)
        assert isinstance(doc_id, DocumentId)

    def test_new_generates_distinct_ids(self) -> None:
        assert DocumentId.new() != DocumentId.new()

    def test_from_str_reconstructs_the_same_id(self) -> None:
        original = DocumentId.new()
        assert DocumentId.from_str(str(original)) == original

    def test_from_str_rejects_a_malformed_string(self) -> None:
        with pytest.raises(ValueError, match="badly formed"):
            DocumentId.from_str("not-a-uuid")
