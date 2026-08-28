from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from config.logging import DisallowedLogFieldError, configure_logging, log_event


class TestLogEvent:
    def test_disallowed_field_is_refused(self) -> None:
        configure_logging()
        with pytest.raises(DisallowedLogFieldError):
            log_event("op_completed", document_content="leaked text")

    def test_the_allowlist_survives_python_optimize(self) -> None:
        """Regression: the check was an `assert`, which `-O` strips — so US-R11's
        allowlist was a no-op in exactly the deployment that enabled the flag, and
        `document_content` would have been written straight to the log line.

        Runs in a subprocess because `-O` is an interpreter-start flag: it decides what
        bytecode gets compiled, so it cannot be turned on from inside this one.
        """
        program = (
            "from config.logging import DisallowedLogFieldError, log_event\n"
            "try:\n"
            "    log_event('op_completed', document_content='leaked text')\n"
            "except DisallowedLogFieldError:\n"
            "    print('refused')\n"
        )
        # S603: the whole command is literal — this interpreter, plus the program
        # spelled out above. Nothing here comes from outside the test.
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-O", "-c", program],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).parents[3] / "app",
        )

        assert result.stdout.strip() == "refused"

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
            error_reason="token=" + "a" * 50,
        )
        captured = capsys.readouterr()
        assert "a" * 50 not in captured.out
        assert "<token>" in captured.out


class TestOnlyTheFreeTextFieldIsScrubbed:
    """The scrubber backs up the name allowlist for the one field whose content nobody
    chose. Running it over everything would cost more than it protects."""

    def test_a_structured_field_survives_intact(self, capsys: pytest.CaptureFixture[str]) -> None:
        # `request_id` comes verbatim from a caller-supplied header with no length cap,
        # and a 64-character hex trace id matches `_TOKEN_RE` exactly. Scrubbing it would
        # replace the correlation key — the entire point of the field — with `<token>`.
        configure_logging()
        trace_id = "a" * 64

        log_event("op_completed", request_id=trace_id)

        assert trace_id in capsys.readouterr().out

    def test_the_caller_hands_over_the_reason_raw(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Neither call site sanitises anything despite the field's name — both pass the
        # underlying text and let `_redact_value` do the work.
        configure_logging()

        log_event("op_completed", error_reason="reached guest@example.com")

        captured = capsys.readouterr().out
        assert "guest@example.com" not in captured
        assert "<email>" in captured
