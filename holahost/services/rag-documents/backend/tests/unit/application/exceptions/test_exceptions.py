"""Tests for the application-layer, HTTP-facing exception hierarchy.

Every `code` asserted below is the class's own name, and that is the whole point: the
value a consumer branches on, and the value an operator reads out of a log, greps back to
the class that produced it in one step. These assertions are what makes a rename fail
loudly — it is a change to the wire contract, not a refactor.
"""

from __future__ import annotations

from application.exceptions import (
    ApplicationError,
    DocumentParseError,
    EmptyDocumentError,
    InvalidPayloadError,
    MalformedRequestError,
    NotFoundError,
    ParsedTextTooLargeError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
    UploadTooLargeError,
)


class TestApplicationError:
    def test_the_base_is_not_a_published_error(self) -> None:
        # It has an identity like everything else, but nothing publishes it: the base is
        # absent from `ERROR_CONTRACT`, so the handler answers an instance of it with the
        # out-of-contract `InternalError` and never emits this value.
        error = ApplicationError("boom")
        assert error.code == "ApplicationError"
        assert error.details_dict() == {}


class TestUnsupportedMediaTypeError:
    def test_wire_shape(self) -> None:
        error = UnsupportedMediaTypeError(allowed=("application/pdf", "text/plain"))
        assert error.code == "UnsupportedMediaTypeError"
        assert error.details_dict() == {"allowed": ["application/pdf", "text/plain"]}


class TestInvalidPayloadError:
    def test_without_limit_still_carries_the_key(self) -> None:
        # US-R09: one class, one `details` field set. `limit` used to be dropped when it
        # was None, so `details.limit` was a KeyError on some raise sites of the very
        # same error and a value on others.
        error = InvalidPayloadError(field="name")
        assert error.code == "InvalidPayloadError"
        assert error.details_dict() == {"field": "name", "limit": None}

    def test_with_limit(self) -> None:
        error = InvalidPayloadError(field="query", limit=4000)
        assert error.details_dict() == {"field": "query", "limit": 4000}

    def test_one_identity_answers_with_one_set_of_keys(self) -> None:
        # Both `limit` cases, since `None` is a published value and not an absent key.
        shapes = {
            tuple(sorted(error.details_dict()))
            for error in (
                InvalidPayloadError(field="name"),
                InvalidPayloadError(field="query", limit=4000),
            )
        }
        assert shapes == {("field", "limit")}


class TestUploadTooLargeError:
    def test_wire_shape(self) -> None:
        error = UploadTooLargeError(limit=8_388_608, actual=9_000_000)
        assert error.code == "UploadTooLargeError"
        assert error.details_dict() == {"limit": 8_388_608, "actual": 9_000_000}


class TestParsedTextTooLargeError:
    def test_wire_shape(self) -> None:
        error = ParsedTextTooLargeError(limit=200_000, actual=250_000)
        assert error.code == "ParsedTextTooLargeError"
        assert error.details_dict() == {"limit": 200_000, "actual": 250_000}

    def test_does_not_share_an_identity_with_upload_too_large(self) -> None:
        # They used to share one code, so the only thing telling a caller which limit it
        # hit was the status. Two errors, two identities.
        assert (
            UploadTooLargeError(limit=1, actual=2).code
            != ParsedTextTooLargeError(limit=1, actual=2).code
        )


class TestEmptyDocumentError:
    def test_wire_shape(self) -> None:
        error = EmptyDocumentError(min_chars=200)
        assert error.code == "EmptyDocumentError"
        assert error.details_dict() == {"min_chars": 200}


class TestDocumentParseError:
    def test_has_its_own_identity_and_no_details(self) -> None:
        # Shared `InvalidPayloadError`'s code with `{"field": "file"}` once, so a caller had
        # to read a `details` value to tell "your file is corrupt" from "your name is
        # too long".
        error = DocumentParseError()
        assert error.code == "DocumentParseError"
        assert error.details_dict() == {}


class TestMalformedRequestError:
    def test_has_its_own_identity_and_stays_mute(self) -> None:
        error = MalformedRequestError()
        assert error.code == "MalformedRequestError"
        assert error.details_dict() == {}


class TestTooManyChunksError:
    def test_wire_shape(self) -> None:
        error = TooManyChunksError(limit=500, actual=501)
        assert error.code == "TooManyChunksError"
        assert error.details_dict() == {"limit": 500, "actual": 501}


class TestNotFoundError:
    def test_wire_shape(self) -> None:
        error = NotFoundError()
        assert error.code == "NotFoundError"
        assert error.details_dict() == {}
