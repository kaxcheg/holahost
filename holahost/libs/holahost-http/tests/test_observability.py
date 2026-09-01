"""The completion event written for a request refused before routing."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from holahost_observability import configure_logging
from starlette.types import Scope

from holahost_http import log_rejection


def _scope(**state: Any) -> Scope:
    return {"type": "http", "method": "POST", "path": "/api/svc/things", "state": state}


def _emitted(captured: str) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(captured.strip().splitlines()[-1])
    return parsed


class TestWhatItRecords:
    def test_it_reports_the_route_the_outcome_and_the_caller(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging()
        token = type("T", (), {"client_id": "guest-reply-cli", "subject": "guest-reply-cli"})()

        log_rejection(
            _scope(request_id="r-1", start_time=0.0, token=token),
            outcome="RateLimitExceededError",
            detail="over quota",
        )

        event = _emitted(capsys.readouterr().out)
        assert event["route"] == "POST /api/svc/things"
        assert event["outcome"] == "RateLimitExceededError"
        assert event["request_id"] == "r-1"
        assert event["client_id"] == "guest-reply-cli"
        assert event["sub"] == "guest-reply-cli"

    def test_an_auth_failure_carries_no_caller(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Authentication is the only writer of `state["token"]`, so a refusal from it —
        # or from anything ahead of it — has no caller identity to report. The fields are
        # present and null rather than absent: one event, one field set.
        configure_logging()

        log_rejection(
            _scope(request_id="r-2", start_time=0.0), outcome="401", detail="expired token"
        )

        event = _emitted(capsys.readouterr().out)
        assert event["client_id"] is None
        assert event["sub"] is None

    def test_it_is_a_warning_whatever_the_outcome(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Everything this can be handed is the caller's own doing — a missing header, bad
        # credentials, an over-quota caller, an oversized body. None is the service
        # failing, and none reaches 5xx.
        configure_logging()

        log_rejection(_scope(start_time=0.0), outcome="413")

        assert _emitted(capsys.readouterr().out)["level"] == logging.getLevelName(logging.WARNING)

    def test_a_scope_without_a_timer_still_logs(self, capsys: pytest.CaptureFixture[str]) -> None:
        # `RequestIdMiddleware` is outermost and always sets it, so this is defence
        # against a stack assembled in the wrong order — which must not turn a refusal
        # into an unlogged crash inside the logger.
        configure_logging()

        log_rejection(_scope(), outcome="401")

        assert _emitted(capsys.readouterr().out)["duration_ms"] == 0.0

    def test_the_detail_is_scrubbed_at_the_sink(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The caller passes its reason raw; `error_reason` is the one free-text field and
        # the logger is what sanitises it.
        configure_logging()

        log_rejection(_scope(start_time=0.0), outcome="401", detail="rejected " + "a" * 50)

        assert _emitted(capsys.readouterr().out)["error_reason"] == "rejected <token>"
