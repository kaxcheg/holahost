"""Anthropic, through `langchain-anthropic`.

The vendor's protocol takes no caller-chosen request identifier that it would record, so the
request's `X-Request-ID` is not sent: it stays in this service's own log lines.
"""

from __future__ import annotations

from collections.abc import Mapping

import anthropic
from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr

from application.ports.exceptions import ProviderRejectedRequestError, TransientProviderError
from domain.value_objects.finish_reason import FinishReason

_FINISH_REASONS: dict[str, FinishReason] = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "max_tokens": FinishReason.MAX_TOKENS,
    # Cut off by the context window rather than by `max_tokens`. After the pre-flight check only a
    # wrong `max_context` in the registry lets this happen, and to the caller it is the same: an
    # answer truncated by a limit.
    "model_context_window_exceeded": FinishReason.MAX_TOKENS,
}
_REFUSAL = "refusal"
# Always passed explicitly: left unset, langchain-anthropic takes the endpoint from
# `ANTHROPIC_API_URL`, `ANTHROPIC_BASE_URL` or `LANGSMITH_GATEWAY`, and a stray variable would send
# the prompts and the provider key elsewhere.
_ENDPOINT = "https://api.anthropic.com"
# Connecting, sending the request, waiting for a pooled connection: each is bounded apart from the
# answer, and each is over well within it.
_SETUP_SECONDS = 1.0
# The vendor's own "try again" statuses; every 5xx, its 529 overload included, is transient too.
_TRANSIENT_STATUSES = frozenset({408, 409, 429})


class AnthropicDialect:
    def chat_model(
        self, model_id: str, api_key: SecretStr, *, base_url: str | None
    ) -> ChatAnthropic:
        # `max_retries=0`: retries, failover and the time budget are the use case's, and an SDK
        # repeating behind its back would spend the deadline twice.
        return ChatAnthropic(
            model=model_id, api_key=api_key, max_retries=0, base_url=base_url or _ENDPOINT
        )

    def timeout(self, seconds: float) -> anthropic.Timeout:
        # The SDK bounds each phase of a call on its own, so one figure would give every phase the
        # whole attempt. The answer gets all of it — pre-flight measured the generation against
        # that, and a shorter wait would cut off an answer it accepted, paid for and then lost. The
        # setup's bound comes on top: at worst `seconds` plus a few seconds, within what the
        # request's deadline leaves before the gateway's ceiling.
        setup = min(_SETUP_SECONDS, seconds)
        return anthropic.Timeout(seconds, connect=setup, write=setup, pool=setup)

    def finish_reason(self, stop_reason: object) -> FinishReason | None:
        return _FINISH_REASONS.get(stop_reason) if isinstance(stop_reason, str) else None

    def is_refusal(self, stop_reason: object) -> bool:
        return stop_reason == _REFUSAL

    def reports_usage(self, response_metadata: Mapping[str, object]) -> bool:
        return response_metadata.get("usage") is not None

    def translate(self, error: Exception) -> TransientProviderError | ProviderRejectedRequestError:
        # `APITimeoutError` is an `APIConnectionError`. Neither carries a status and both count as a
        # timeout: a refused connection is not charged for, but it is the rarer of the two.
        if isinstance(error, anthropic.APIConnectionError):
            return TransientProviderError(type(error).__name__, status=None, retry_after=None)
        if isinstance(error, anthropic.APIStatusError):
            status = error.status_code
            message = _account(error)
            if status in _TRANSIENT_STATUSES or status >= 500:
                retry_after = _seconds(error.response.headers.get("retry-after"))
                return TransientProviderError(message, status=status, retry_after=retry_after)
            return ProviderRejectedRequestError(message, status=status)
        # Not the vendor's: a response the integration could not read, a call built wrong — this
        # service's own defect at this vendor, which another candidate may not share. Its type
        # alone: a parser's error can quote the answer it could not read.
        return ProviderRejectedRequestError(type(error).__name__, status=None)


def _account(error: anthropic.APIStatusError) -> str:
    """The failed call as the vendor described it, for the log: its error type and message, and the
    request id its support asks for.

    The vendor's messages name what is wrong with the request — a field, a limit — without quoting
    it. A body that is not the vendor's own, such as a proxy's error page, is left out.
    """
    account = f"{type(error).__name__} ({error.status_code})"
    vendor = error.body.get("error") if isinstance(error.body, dict) else None
    if isinstance(vendor, dict):
        account += f" {vendor.get('type')}: {vendor.get('message')}"
    if error.request_id is not None:
        account += f" [request-id {error.request_id}]"
    return account


def _seconds(retry_after: str | None) -> float | None:
    """A `Retry-After` in seconds; its HTTP-date form is left to the backoff formula."""
    if retry_after is None:
        return None
    try:
        return float(retry_after)
    except ValueError:
        return None
