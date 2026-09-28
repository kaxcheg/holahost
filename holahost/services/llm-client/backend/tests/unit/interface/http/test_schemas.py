"""The request and response models of `POST /generate`."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from application.dto.generation import GenerateResult
from application.limits import MAX_OUTPUT_TOKENS
from interface.http.schemas import GenerateRequest, GenerateResponse


def _request(**fields: object) -> GenerateRequest:
    body: dict[str, object] = {
        "model": "fast",
        "messages": [{"role": "user", "content": "What time is check-in?"}],
    }
    return GenerateRequest.model_validate({**body, **fields})


def _result(**fields: object) -> GenerateResult:
    values: dict[str, object] = {
        "text": "From 15:00.",
        "input_tokens": 120,
        "output_tokens": 8,
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "finish_reason": "stop",
        "downgraded": False,
        "failed_over": False,
        "attempts": 1,
        "provider_timeouts": 0,
        "provider_ms": 900,
    }
    return GenerateResult(**{**values, **fields})  # type: ignore[arg-type]


class TestGenerateRequest:
    def test_optional_fields_default_to_absent_and_system_to_empty(self) -> None:
        body = _request()

        assert body.system == ""
        assert (body.max_tokens, body.temperature, body.stop) == (None, None, None)
        assert body.messages[0].content == "What time is check-in?"

    def test_a_misspelt_field_is_refused_rather_than_ignored(self) -> None:
        # Ignored, `max_token` would serve the request with the default ceiling the caller
        # meant to change.
        with pytest.raises(ValidationError):
            _request(max_token=5)

    def test_a_misspelt_message_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _request(messages=[{"role": "user", "text": "hi"}])

    def test_the_ceiling_is_published_but_left_to_the_use_case(self) -> None:
        # The use case truncates a larger value; a schema bound would refuse it first.
        assert _request(max_tokens=5000).max_tokens == 5000
        schema = GenerateRequest.model_json_schema()["properties"]["max_tokens"]
        assert str(MAX_OUTPUT_TOKENS) in schema["description"]

    @pytest.mark.parametrize(
        "fields", [{"temperature": True}, {"max_tokens": True}, {"max_tokens": 5.0}]
    )
    def test_a_wrong_type_is_refused_rather_than_coerced(self, fields: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            GenerateRequest.model_validate_json(
                json.dumps({"model": "fast", "messages": [], **fields})
            )

    def test_an_integer_temperature_is_a_number_all_the_same(self) -> None:
        body = GenerateRequest.model_validate_json(
            json.dumps({"model": "fast", "messages": [], "temperature": 1})
        )
        assert body.temperature == 1.0

    def test_ranges_are_judged_by_the_use_case_not_the_schema(self) -> None:
        # One owner per rule, so an out-of-range value answers with one `details.field`.
        body = _request(temperature=3.0, stop=[""], messages=[])
        assert (body.temperature, body.stop, body.messages) == (3.0, [""], [])


class TestGenerateResponse:
    def test_nests_usage_and_leaves_the_event_only_figures_out(self) -> None:
        response = GenerateResponse.from_result(_result(downgraded=True))

        assert response.model_dump() == {
            "text": "From 15:00.",
            "usage": {"input_tokens": 120, "output_tokens": 8},
            "provider": "anthropic",
            "model": "claude-haiku-4-5",
            "finish_reason": "stop",
            "downgraded": True,
            "failed_over": False,
        }

    def test_a_finish_reason_outside_the_enumeration_is_a_defect(self) -> None:
        with pytest.raises(ValidationError):
            GenerateResponse.from_result(_result(finish_reason="tool_use"))
