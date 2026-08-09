"""Tests for the application-layer, HTTP-facing exception hierarchy."""

from __future__ import annotations

from application.exceptions import (
    ApplicationError,
    DocumentParseError,
    EmptyDocumentError,
    InvalidPayloadError,
    NotFoundError,
    ParsedTextTooLargeError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
    UploadTooLargeError,
)


class TestApplicationError:
    def test_default_code(self) -> None:
        error = ApplicationError("boom")
        assert error.code == "ERR_INTERNAL"
        assert error.details_dict() == {}


class TestUnsupportedMediaTypeError:
    def test_wire_shape(self) -> None:
        error = UnsupportedMediaTypeError(allowed=("application/pdf", "text/plain"))
        assert error.code == "ERR_UNSUPPORTED_MEDIA_TYPE"
        assert error.details_dict() == {"allowed": ["application/pdf", "text/plain"]}


class TestInvalidPayloadError:
    def test_without_limit(self) -> None:
        error = InvalidPayloadError(field="name")
        assert error.code == "ERR_INVALID_PAYLOAD"
        assert error.details_dict() == {"field": "name"}

    def test_with_limit(self) -> None:
        error = InvalidPayloadError(field="query", limit=4000)
        assert error.details_dict() == {"field": "query", "limit": 4000}


class TestUploadTooLargeError:
    def test_wire_shape(self) -> None:
        error = UploadTooLargeError(limit=8_388_608, actual=9_000_000)
        assert error.code == "ERR_PAYLOAD_TOO_LARGE"
        assert error.details_dict() == {"limit": 8_388_608, "actual": 9_000_000}


class TestParsedTextTooLargeError:
    def test_wire_shape(self) -> None:
        error = ParsedTextTooLargeError(limit=200_000, actual=250_000)
        assert error.code == "ERR_PAYLOAD_TOO_LARGE"
        assert error.details_dict() == {"limit": 200_000, "actual": 250_000}

    def test_shares_code_with_upload_too_large_error(self) -> None:
        upload = UploadTooLargeError(limit=1, actual=2)
        parsed = ParsedTextTooLargeError(limit=1, actual=2)
        assert upload.code == parsed.code


class TestEmptyDocumentError:
    def test_wire_shape(self) -> None:
        error = EmptyDocumentError(min_chars=200)
        assert error.code == "ERR_EMPTY_DOCUMENT"
        assert error.details_dict() == {"min_chars": 200}


class TestDocumentParseError:
    def test_shares_code_with_invalid_payload_error(self) -> None:
        error = DocumentParseError()
        assert error.code == "ERR_INVALID_PAYLOAD"
        assert error.details_dict() == {"field": "file"}


class TestTooManyChunksError:
    def test_wire_shape(self) -> None:
        error = TooManyChunksError(limit=500, actual=501)
        assert error.code == "ERR_TOO_MANY_CHUNKS"
        assert error.details_dict() == {"limit": 500, "actual": 501}


class TestNotFoundError:
    def test_wire_shape(self) -> None:
        error = NotFoundError()
        assert error.code == "ERR_NOT_FOUND"
        assert error.details_dict() == {}
