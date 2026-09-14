"""This service's half of the logging contract.

The mechanism — the allowlist raising rather than dropping, its survival under `-O`, the
scrubber, the core field set — is `holahost-observability`'s and is tested there. What is
left to check here is the declaration: that this service's own fields are accepted, and
that content is not.

Grows with `SERVICE_LOG_FIELDS`: a field added there without a line here is a field nobody
ever proved reaches a log line.
"""

from __future__ import annotations

import pytest

from config.logging import DisallowedLogFieldError, configure_logging, log_event


class TestTheServicesOwnFields:
    def test_the_platform_core_is_accepted(self) -> None:
        configure_logging()

        log_event(
            "op_completed",
            request_id="r-1",
            client_id="cli-1",
            sub="user-123",
            route="GET /health",
            outcome="success",
            duration_ms=41.2,
        )

    def test_content_is_refused(self) -> None:
        """The protection is structural: nothing inspects a value, so what keeps document
        text, prompt text, a query or a token body out of the log is that their field names
        were never declared.

        Literal keyword arguments rather than a parametrised `**{field: ...}` splat: mypy
        rejects splatting a `dict[str, str]` past `log_event`'s keyword-only `level: int`.
        """
        configure_logging()

        with pytest.raises(DisallowedLogFieldError):
            log_event("op_completed", query="leaked")
        with pytest.raises(DisallowedLogFieldError):
            log_event("op_completed", token="leaked")
