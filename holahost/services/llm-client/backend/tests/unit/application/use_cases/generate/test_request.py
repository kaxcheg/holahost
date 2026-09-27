"""GenerateUseCase: the command is judged before any port is asked, and the request reaches the
provider exactly as it was sent."""

from __future__ import annotations

import pytest
from tests._support.builders import HAIKU, make_cmd, make_generation, make_usage
from tests._support.generate import build_use_case, ok

from application.dto.generation import GenerateResult, MessageInput
from application.exceptions import InvalidPayloadError, UnknownModelError
from domain.value_objects.message import Message
from domain.value_objects.role import Role


class TestTheCommandIsJudgedBeforeAnyPort:
    def test_empty_messages_are_invalid(self) -> None:
        h = build_use_case()
        with pytest.raises(InvalidPayloadError) as exc:
            h.use_case.execute(make_cmd(messages=[]))
        assert exc.value.field == "messages"
        assert h.generation.calls == []
        assert h.budgets.reads == []

    def test_an_unknown_role_is_invalid(self) -> None:
        h = build_use_case()
        with pytest.raises(InvalidPayloadError) as exc:
            h.use_case.execute(make_cmd(messages=[MessageInput(role="assistant", text="Hello")]))
        assert exc.value.field == "messages"
        assert h.generation.calls == []

    def test_a_blank_message_is_invalid(self) -> None:
        h = build_use_case()
        with pytest.raises(InvalidPayloadError) as exc:
            h.use_case.execute(make_cmd(messages=[MessageInput(role="user", text="   ")]))
        assert exc.value.field == "messages"

    def test_a_key_over_the_limit_is_invalid(self) -> None:
        h = build_use_case()
        with pytest.raises(InvalidPayloadError) as exc:
            h.use_case.execute(make_cmd(idempotency_key="k" * 129))
        assert exc.value.details_dict() == {"field": "idempotency_key", "limit": 128}
        assert h.idempotency.begun == []

    def test_an_empty_key_is_invalid(self) -> None:
        h = build_use_case()
        with pytest.raises(InvalidPayloadError) as exc:
            h.use_case.execute(make_cmd(idempotency_key=""))
        assert exc.value.field == "idempotency_key"

    def test_a_zero_max_tokens_is_invalid(self) -> None:
        # Not truncated like a too-large value: passed on, it would buy a vendor's rejection — a
        # 500 with an empty body — for a mistake the caller can fix.
        h = build_use_case()
        with pytest.raises(InvalidPayloadError) as exc:
            h.use_case.execute(make_cmd(max_tokens=0))
        assert exc.value.details_dict() == {"field": "max_tokens", "limit": 1000}
        assert h.generation.calls == []

    def test_a_negative_max_tokens_is_invalid(self) -> None:
        h = build_use_case()
        with pytest.raises(InvalidPayloadError) as exc:
            h.use_case.execute(make_cmd(max_tokens=-5))
        assert exc.value.field == "max_tokens"


class TestModelResolution:
    def test_an_unknown_model_lists_the_aliases(self) -> None:
        h = build_use_case(aliases=["default", "fast"])
        with pytest.raises(UnknownModelError) as exc:
            h.use_case.execute(make_cmd(model_ref="huge", idempotency_key="k-1"))
        assert exc.value.details_dict() == {
            "requested": "huge",
            "available_aliases": ["default", "fast"],
        }
        assert h.idempotency.begun == []
        assert h.generation.calls == []

    def test_a_pinned_model_id_calls_that_model(self) -> None:
        h = build_use_case(routes={"claude-haiku-4-5": [HAIKU]})
        result = h.use_case.execute(make_cmd(model_ref="claude-haiku-4-5"))
        assert result.model == "claude-haiku-4-5"


class TestHappyPath:
    def test_returns_the_answer_with_the_model_that_answered(self) -> None:
        answer = make_generation(text="From 15:00.", usage=make_usage(120, 30))
        h = build_use_case(script={HAIKU.id.value: [ok(1.0, generation=answer)]})

        result = h.use_case.execute(make_cmd())

        assert result == GenerateResult(
            text="From 15:00.",
            input_tokens=120,
            output_tokens=30,
            provider="anthropic",
            model="claude-haiku-4-5",
            finish_reason="stop",
            downgraded=False,
            failed_over=False,
            attempts=1,
            provider_timeouts=0,
            provider_ms=1000,
        )

    def test_the_request_reaches_the_provider_unchanged(self) -> None:
        # The caller's injection defence depends on it: roles, order and text as sent, and no
        # instruction of the service's own.
        h = build_use_case()
        messages = [
            MessageInput(role="user", text="First"),
            MessageInput(role="user", text="Second"),
        ]

        h.use_case.execute(
            make_cmd(
                system="  Keep it short.  ",
                messages=messages,
                temperature=0.3,
                stop=["\n\n"],
                request_id="req-9",
            )
        )

        call = h.generation.calls[0]
        assert call.system == "  Keep it short.  "
        assert call.messages == [
            Message(role=Role.USER, text="First"),
            Message(role=Role.USER, text="Second"),
        ]
        assert (call.temperature, call.stop, call.request_id) == (0.3, ["\n\n"], "req-9")
