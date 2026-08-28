"""The two declarations of one error contract must agree.

`application/exceptions` declares each error — its identity (class name) and its
`details` shape (`details_dict()`). `interface/http/error_schemas` declares the same
thing as Pydantic models, which is what puts it into `docs/openapi.json`. The layering
forbids merging them (the application layer must not depend on a serialization library),
so this file is what stops them drifting: rename an error class, add a `details` key, or
change one without the other, and one of these fails.
"""

from __future__ import annotations

import pytest
from holahost_http import error_envelope
from holahost_http.errors import PlatformError
from pydantic import BaseModel

from application.exceptions import (
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
from interface.http.error_schemas import (
    DocumentParseErrorBody,
    EmptyDocumentErrorBody,
    InvalidPayloadErrorBody,
    MalformedRequestErrorBody,
    NotFoundErrorBody,
    ParsedTextTooLargeErrorBody,
    TooManyChunksErrorBody,
    UnsupportedMediaTypeErrorBody,
    UploadTooLargeErrorBody,
)
from interface.http.errors import ERROR_CONTRACT

# One sample per published error, paired with the model that publishes it. Both `limit`
# cases of InvalidPayloadError are here because `None` is a published value, not an
# absent key.
_PUBLISHED: list[tuple[PlatformError, type[BaseModel]]] = [
    (UnsupportedMediaTypeError(allowed=("application/pdf",)), UnsupportedMediaTypeErrorBody),
    (InvalidPayloadError(field="name", limit=200), InvalidPayloadErrorBody),
    (InvalidPayloadError(field="query"), InvalidPayloadErrorBody),
    (MalformedRequestError(), MalformedRequestErrorBody),
    (UploadTooLargeError(limit=1, actual=2), UploadTooLargeErrorBody),
    (ParsedTextTooLargeError(limit=1, actual=2), ParsedTextTooLargeErrorBody),
    (EmptyDocumentError(min_chars=200), EmptyDocumentErrorBody),
    (DocumentParseError(), DocumentParseErrorBody),
    (TooManyChunksError(limit=500, actual=501), TooManyChunksErrorBody),
    (NotFoundError(), NotFoundErrorBody),
]
"""Only this service's own errors. `401`/`503`, `429` and the transport `413` come from
the shared edge and are the platform's contract, identical behind every service — this
document does not restate them (see `error_schemas`)."""


@pytest.mark.parametrize(("error", "model"), _PUBLISHED, ids=lambda x: getattr(x, "__name__", ""))
class TestEachPublishedErrorMatchesItsModel:
    def test_the_envelope_validates(self, error: PlatformError, model: type[BaseModel]) -> None:
        # `extra="forbid"` throughout, so a `details` key nobody published fails here
        # rather than reaching a consumer that has no schema for it.
        envelope = error_envelope(error.code, str(error), error.details_dict())
        model.model_validate(envelope["error"])

    def test_the_identity_matches(self, error: PlatformError, model: type[BaseModel]) -> None:
        # The anti-rename guard: `code` is derived from the class name, and the model
        # pins it as a Literal. Rename the class and this fails — which is the whole
        # point of deriving rather than declaring.
        published = model.model_fields["code"].annotation
        assert published is not None
        assert error.code in getattr(published, "__args__", ())


def test_every_error_in_the_contract_has_a_model() -> None:
    """`ERROR_CONTRACT` is what the handler will answer with; nothing in it may be
    missing from the published schema."""
    covered = {type(error) for error, _ in _PUBLISHED}
    assert set(ERROR_CONTRACT) <= covered
