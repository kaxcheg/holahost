"""This service's half of the logging contract.

The mechanism — the allowlist raising rather than dropping, its survival under `-O`, the
scrubber, the core field set — is `holahost-observability`'s and is tested there. What is
left to check here is the declaration: that this service's own fields are accepted, and
that the four that must never be logged are not.
"""

from __future__ import annotations

import pytest

from config.logging import DisallowedLogFieldError, configure_logging, log_event


class TestTheServicesOwnFields:
    def test_every_declared_field_is_accepted(self) -> None:
        configure_logging()

        log_event(
            "op_completed",
            request_id="r-1",
            client_id="guest-reply-cli",
            sub="guest-reply-cli",
            route="POST /documents",
            outcome="success",
            duration_ms=41.2,
            document_id="8f14e45f-ceea-467a-9f0a-1c2d3e4f5a6b",
            chunk_count=128,
            hits=5,
            top_score=0.71,
            stage_ms={"parse": 1.0, "chunk": 2.0, "embed": 3.0, "persist": 4.0},
        )

    def test_sensitive_fields_are_refused(self) -> None:
        """The four fields that must never be logged. None is declared, so each raises —
        the point being that the protection is structural: nothing here inspects a value.

        Literal keyword arguments rather than a parametrised `**{field: ...}` splat:
        mypy rejects splatting a `dict[str, str]` past `log_event`'s keyword-only
        `level: int`, the same reason `router._log_success` spells its fields out.
        """
        configure_logging()

        with pytest.raises(DisallowedLogFieldError):
            log_event("op_completed", document_content="leaked")
        with pytest.raises(DisallowedLogFieldError):
            log_event("op_completed", chunk_text="leaked")
        with pytest.raises(DisallowedLogFieldError):
            log_event("op_completed", query="leaked")
        with pytest.raises(DisallowedLogFieldError):
            log_event("op_completed", token="leaked")
