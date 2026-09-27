"""Tests for the generation DTOs."""

from __future__ import annotations

import dataclasses

import pytest

from application.dto.generation import GenerateCmd, GenerateResult, MessageInput


def _cmd() -> GenerateCmd:
    return GenerateCmd(
        client_id="guest-reply-cli",
        subject="guest-reply-cli",
        request_id="req-1",
        model_ref="fast",
        system="You answer guests.",
        messages=[MessageInput(role="user", text="What time is check-in?")],
        max_tokens=None,
        temperature=None,
        stop=None,
        idempotency_key=None,
    )


class TestMessageInput:
    def test_frozen(self) -> None:
        message = MessageInput(role="user", text="hi")
        with pytest.raises(dataclasses.FrozenInstanceError):
            message.text = "other"  # type: ignore[misc]


class TestGenerateCmd:
    def test_frozen(self) -> None:
        cmd = _cmd()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.model_ref = "other"  # type: ignore[misc]


class TestGenerateResult:
    def test_frozen(self) -> None:
        result = GenerateResult(
            text="Check-in is from 15:00.",
            input_tokens=120,
            output_tokens=30,
            provider="anthropic",
            model="claude-haiku-4-5",
            finish_reason="stop",
            downgraded=False,
            failed_over=False,
            attempts=1,
            provider_timeouts=0,
            provider_ms=900,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.text = "other"  # type: ignore[misc]
