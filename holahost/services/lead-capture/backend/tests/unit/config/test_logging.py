from __future__ import annotations

import json
import logging

import pytest
from pydantic import SecretStr

from config.logging import configure_logging, log_event


def test_log_event_emits_json_with_allowlisted_fields(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    log_event(
        "http_request_completed",
        request_id="r-1",
        endpoint="/api/capture-lead/generate",
        method="POST",
        status=200,
        duration_ms=42,
    )
    line = capsys.readouterr().err.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "http_request_completed"
    assert record["level"] == "INFO"
    assert "timestamp" in record
    assert record["request_id"] == "r-1"
    assert record["status"] == 200


def test_log_event_level_is_caller_determined(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    log_event("http_request_completed", level=logging.ERROR, status=500)
    record = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    # The call site — not the helper — chooses severity; ERROR makes the CloudWatch
    # error_count filter (level=ERROR, §10.5) match.
    assert record["level"] == "ERROR"
    assert record["event"] == "http_request_completed"


def test_log_event_rejects_non_allowlisted_field() -> None:
    configure_logging()
    with pytest.raises(AssertionError):
        log_event("bad_event", email="leak@example.com")  # 'email' is denied (§10.5)


def test_log_event_redacts_secret_values_and_sanitizes_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()
    log_event(
        "http_request_failed",
        error_code="ERR_X",
        error_message_sanitized="reach me at bob@example.com",
        ip_hash=SecretStr("super-secret"),  # a SecretStr value must never reach the log raw
    )
    record = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert record["ip_hash"] == "<redacted>"
    assert "bob@example.com" not in record["error_message_sanitized"]
    assert "<email>" in record["error_message_sanitized"]


def test_log_event_scrubs_opaque_token_in_message(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    token = "x" * 48  # opaque token ≥40 chars → _TOKEN_RE scrub (36-char UUIDs stay unmatched)
    log_event(
        "http_request_failed", error_code="ERR_X", error_message_sanitized=f"leaked {token} here"
    )
    record = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert token not in record["error_message_sanitized"]
    assert "<token>" in record["error_message_sanitized"]
