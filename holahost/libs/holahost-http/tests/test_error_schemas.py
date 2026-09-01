"""The platform's errors and the models that publish them must agree."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from holahost_http import (
    INTERNAL_ERROR_CODE,
    InvalidPayloadError,
    MalformedRequestError,
    NotFoundError,
    PlatformError,
    error_envelope,
)
from holahost_http.error_schemas import (
    INTERNAL_RESPONSES,
    InternalErrorBody,
    InvalidPayloadErrorBody,
    MalformedRequestErrorBody,
    NoDetails,
    NotFoundErrorBody,
    Strict,
    envelope,
)

_PUBLISHED: list[tuple[PlatformError, type[BaseModel]]] = [
    # Both `limit` cases: `None` is a published value, not an absent key.
    (InvalidPayloadError(field="name", limit=200), InvalidPayloadErrorBody),
    (InvalidPayloadError(field="query"), InvalidPayloadErrorBody),
    (MalformedRequestError(), MalformedRequestErrorBody),
    (NotFoundError(), NotFoundErrorBody),
]


@pytest.mark.parametrize(("error", "model"), _PUBLISHED, ids=lambda x: getattr(x, "__name__", ""))
class TestEachPlatformErrorMatchesItsModel:
    def test_the_published_half_of_the_envelope_validates(
        self, error: PlatformError, model: type[BaseModel]
    ) -> None:
        # `message` is dropped before validating, and that is the assertion: it is on the
        # wire for a human and is deliberately not in the model, so `extra="forbid"`
        # rejects it. Everything else must validate exactly — a `details` key nobody
        # published fails here rather than reaching a consumer with no schema for it.
        body = dict(error_envelope(error.code, str(error), error.details_dict())["error"])  # type: ignore[call-overload]
        assert body.pop("message")

        model.model_validate(body)

    def test_the_identity_matches(self, error: PlatformError, model: type[BaseModel]) -> None:
        # The anti-rename guard: `code` is derived from the class name and the model pins
        # it as a Literal. Rename the class and this fails, which is the whole point of
        # deriving rather than declaring.
        published = model.model_fields["code"].annotation
        assert published is not None
        assert error.code in getattr(published, "__args__", ())


def test_the_message_is_never_published() -> None:
    """It is not contract: a consumer branches on `code` and composes what it shows from
    `details`. Publishing it would invite exactly the parsing the contract forbids."""
    for _, model in _PUBLISHED:
        assert "message" not in model.model_fields
    assert "message" not in InternalErrorBody.model_fields


def test_the_internal_identity_matches_the_constant() -> None:
    """`InternalErrorBody` spells the string out because a `Literal` of a name is not a
    type to a checker; this is what keeps the two in step."""
    published = InternalErrorBody.model_fields["code"].annotation
    assert published is not None
    assert INTERNAL_ERROR_CODE in getattr(published, "__args__", ())


def test_the_internal_response_is_offered_for_500() -> None:
    assert set(INTERNAL_RESPONSES) == {500}


class TestStrictness:
    def test_an_undeclared_key_is_refused(self) -> None:
        with pytest.raises(ValueError, match="extra"):
            NoDetails.model_validate({"unexpected": 1})

    def test_the_envelope_factory_wraps_a_body_under_error(self) -> None:
        wrapper = envelope("Wrapped", NotFoundErrorBody)

        assert issubclass(wrapper, Strict)
        wrapper.model_validate({"error": {"code": "NotFoundError", "details": {}}})
