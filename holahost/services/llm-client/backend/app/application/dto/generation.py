"""Command and result for generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MessageInput:
    """One message of the command, as the caller sent it.

    :param role: The author's role; only `user` is accepted.
    :param text: The message text.
    """

    role: str
    text: str


@dataclass(frozen=True)
class GenerateCmd:
    """Command for POST /api/llm-client/generate.

    `client_id` and `subject` come from the validated token, never from the request body.

    :param client_id: The token's `client_id`.
    :param subject: The token's `sub`.
    :param request_id: The request's `X-Request-ID`, for correlating the usage record with the logs.
    :param model_ref: An alias or a model identifier.
    :param system: The system instruction, passed to the provider unchanged.
    :param messages: The conversation, in order.
    :param max_tokens: The requested ceiling on the answer; `None` when not sent.
    :param temperature: `None` when not sent.
    :param stop: Stop sequences; `None` when not sent.
    :param idempotency_key: The `Idempotency-Key` header; `None` when not sent.
    """

    client_id: str
    subject: str
    request_id: str
    model_ref: str
    system: str
    messages: list[MessageInput]
    max_tokens: int | None
    temperature: float | None
    stop: list[str] | None
    idempotency_key: str | None


@dataclass(frozen=True)
class GenerateResult:
    """A generation's output.

    `provider` and `model` are the ones that answered: `downgraded` and `failed_over` say why they
    may differ from what was asked for. `attempts`, `provider_timeouts` and `provider_ms` are not
    part of the response — they are what the completion event reports.

    :param text: The answer.
    :param input_tokens: The provider's count.
    :param output_tokens: The provider's count.
    :param provider: The provider that answered.
    :param model: The model that answered.
    :param finish_reason: `stop` or `max_tokens`.
    :param downgraded: The budget policy moved the request to the cheaper model.
    :param failed_over: A candidate other than the first answered.
    :param attempts: Provider calls made, across every candidate.
    :param provider_timeouts: Attempts cut off by the service's own timeout — most likely charged by
        the provider without the spend reaching the usage log.
    :param provider_ms: Time spent inside provider calls, across every attempt.
    """

    text: str
    input_tokens: int
    output_tokens: int
    provider: str
    model: str
    finish_reason: str
    downgraded: bool
    failed_over: bool
    attempts: int
    provider_timeouts: int
    provider_ms: int
