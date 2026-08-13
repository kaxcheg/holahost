from __future__ import annotations

import pytest

from config.logging import configure_logging, log_event


class TestLogEvent:
    def test_disallowed_field_raises_assertion_error(self) -> None:
        configure_logging()
        with pytest.raises(AssertionError):
            log_event("op_completed", document_content="leaked text")

    def test_allowed_fields_are_accepted(self) -> None:
        configure_logging()
        log_event(
            "op_completed", request_id="r-1", route="/documents", outcome="201", duration_ms=42
        )

    def test_bearer_token_like_value_is_redacted(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The handler writes JSON straight to stdout (§3.4), and the logger has
        # `propagate = False` — `caplog` relies on propagation to the root logger
        # and never sees these records, so this reads the real stdout write instead.
        configure_logging()
        log_event(
            "startup_completed",
            error_message_sanitized="token=" + "a" * 50,
        )
        captured = capsys.readouterr()
        assert "a" * 50 not in captured.out
        assert "<token>" in captured.out
