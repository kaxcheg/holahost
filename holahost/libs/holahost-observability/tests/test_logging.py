from __future__ import annotations

import subprocess
import sys

import pytest

from holahost_observability import (
    CORE_LOG_FIELDS,
    DisallowedLogFieldError,
    configure_logging,
    log_event,
)


class TestTheAllowlist:
    def test_a_field_outside_it_is_refused(self) -> None:
        configure_logging()

        with pytest.raises(DisallowedLogFieldError):
            log_event("op_completed", document_content="leaked text")

    def test_core_fields_are_accepted_without_declaring_anything(self) -> None:
        configure_logging()

        log_event(
            "op_completed", request_id="r-1", route="/documents", outcome="201", duration_ms=42
        )

    def test_a_service_field_is_accepted_only_once_declared(self) -> None:
        configure_logging()
        with pytest.raises(DisallowedLogFieldError):
            log_event("op_completed", document_id="d-1")

        configure_logging(extra_fields={"document_id"})
        log_event("op_completed", document_id="d-1")

    def test_configuring_again_replaces_the_declaration(self) -> None:
        # Rather than accumulating: an allowlist that grew on every call would let a field
        # survive its own removal.
        configure_logging(extra_fields={"document_id"})
        configure_logging(extra_fields={"chunk_count"})

        with pytest.raises(DisallowedLogFieldError):
            log_event("op_completed", document_id="d-1")

    def test_an_unconfigured_process_falls_back_to_the_core_alone(self) -> None:
        """A service field logged by a process that never configured itself raises; the
        inverse — a field allowed because some step has not run — cannot happen.

        A subprocess, because the allowlist is process state every other test here sets."""
        program = (
            "from holahost_observability import DisallowedLogFieldError, log_event\n"
            "log_event('op_completed', outcome='success')\n"  # core: fine
            "try:\n"
            "    log_event('op_completed', document_id='d-1')\n"
            "except DisallowedLogFieldError:\n"
            "    print('refused')\n"
        )
        # S603: the whole command is literal — this interpreter, plus the program above.
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", program], capture_output=True, text=True, check=True
        )

        assert result.stdout.strip() == "refused"

    def test_it_survives_python_optimize(self) -> None:
        """An `assert` would be stripped by `-O`, making the allowlist a no-op in exactly
        the deployment that sets the flag.

        A subprocess because `-O` decides what bytecode gets compiled, so it cannot be
        turned on from inside this interpreter."""
        program = (
            "from holahost_observability import DisallowedLogFieldError, log_event\n"
            "try:\n"
            "    log_event('op_completed', document_content='leaked text')\n"
            "except DisallowedLogFieldError:\n"
            "    print('refused')\n"
        )
        # S603: as above.
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-O", "-c", program], capture_output=True, text=True, check=True
        )

        assert result.stdout.strip() == "refused"


class TestOnlyTheFreeTextFieldIsScrubbed:
    """The scrubber backs up the name allowlist for the one field whose content nobody
    chose. Running it over everything would cost more than it protects."""

    def test_a_bearer_token_like_value_is_redacted(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The handler writes JSON straight to stdout and the logger has
        # `propagate = False` — `caplog` relies on propagation to the root logger and
        # never sees these records, so this reads the real stdout write instead.
        configure_logging()

        log_event("startup_completed", error_reason="token=" + "a" * 50)

        captured = capsys.readouterr()
        assert "a" * 50 not in captured.out
        assert "<token>" in captured.out

    def test_an_email_address_is_redacted(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging()

        log_event("op_completed", error_reason="reached guest@example.com")

        captured = capsys.readouterr().out
        assert "guest@example.com" not in captured
        assert "<email>" in captured

    def test_a_structured_field_survives_intact(self, capsys: pytest.CaptureFixture[str]) -> None:
        # `request_id` comes verbatim from a caller-supplied header with no length cap,
        # and a 64-character hex trace id matches the token pattern exactly. Scrubbing it
        # would replace the correlation key — the entire point of the field — with
        # `<token>`.
        configure_logging()
        trace_id = "a" * 64

        log_event("op_completed", request_id=trace_id)

        assert trace_id in capsys.readouterr().out


class TestCoreFields:
    def test_the_metric_bearing_fields_are_fixed_here(self) -> None:
        """These names are read by every service's CloudWatch metric filters. Renaming
        one silently stops a filter matching, and `treat_missing_data = notBreaching`
        then reads the dead metric as health — so the set is pinned by a test, not only
        by convention."""
        assert {
            "request_id",
            "client_id",
            "sub",
            "route",
            "outcome",
            "duration_ms",
            "error_reason",
        } == CORE_LOG_FIELDS
