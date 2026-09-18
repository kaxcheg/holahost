"""Tests for the pre-call estimates."""

from __future__ import annotations

from tests._support.builders import make_model

from application.estimates import (
    effective_max_tokens,
    estimate_input_tokens,
    generation_seconds,
    max_tokens_within,
)
from application.limits import MAX_OUTPUT_TOKENS, MESSAGE_FRAMING_TOKENS
from domain.value_objects.message import Message
from domain.value_objects.role import Role


class TestEstimateInputTokens:
    def test_counts_utf8_bytes_plus_framing_per_part(self) -> None:
        messages = [Message(role=Role.USER, text="abc")]
        assert estimate_input_tokens("sys", messages) == 3 + 3 + 2 * MESSAGE_FRAMING_TOKENS

    def test_counts_every_message(self) -> None:
        messages = [Message(role=Role.USER, text="ab"), Message(role=Role.USER, text="cd")]
        assert estimate_input_tokens("", messages) == 4 + 3 * MESSAGE_FRAMING_TOKENS

    def test_cyrillic_counts_two_bytes_per_letter(self) -> None:
        # The bound is bytes, not characters: a token never spans less than one byte.
        messages = [Message(role=Role.USER, text="привет")]
        assert estimate_input_tokens("", messages) == 12 + 2 * MESSAGE_FRAMING_TOKENS


class TestEffectiveMaxTokens:
    def test_defaults_to_the_output_ceiling(self) -> None:
        assert effective_max_tokens(None, make_model()) == MAX_OUTPUT_TOKENS

    def test_truncates_above_the_ceiling(self) -> None:
        assert effective_max_tokens(MAX_OUTPUT_TOKENS + 500, make_model()) == MAX_OUTPUT_TOKENS

    def test_keeps_a_smaller_request(self) -> None:
        assert effective_max_tokens(200, make_model()) == 200

    def test_the_models_own_ceiling_wins_when_lower(self) -> None:
        model = make_model(max_output=300, max_context=1000)
        assert effective_max_tokens(None, model) == 300
        assert effective_max_tokens(500, model) == 300


class TestGenerationSeconds:
    def test_divides_by_the_models_speed(self) -> None:
        assert generation_seconds(1000, make_model(tokens_per_second=50)) == 20.0


class TestMaxTokensWithin:
    def test_floors_seconds_times_speed(self) -> None:
        assert max_tokens_within(2.759, make_model(tokens_per_second=100)) == 275

    def test_capped_by_the_output_ceiling(self) -> None:
        assert max_tokens_within(60.0, make_model(tokens_per_second=100)) == MAX_OUTPUT_TOKENS

    def test_never_negative(self) -> None:
        assert max_tokens_within(-1.0, make_model()) == 0
