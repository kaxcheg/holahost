"""Builders for valid domain objects, used across application-layer tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from application.dto.generation import GenerateCmd, MessageInput
from application.ports.generation import Generation
from domain.entities.budget import Budget
from domain.entities.model import Model
from domain.entities.provider import Provider
from domain.entities.usage_record import UsageRecord
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from domain.value_objects.finish_reason import FinishReason
from domain.value_objects.generation_id import GenerationId
from domain.value_objects.model_id import ModelId
from domain.value_objects.provider_name import ProviderName
from domain.value_objects.subject import Subject
from domain.value_objects.token_count import TokenCount
from domain.value_objects.usage import Usage

CLIENT = "guest-reply-cli"
WINDOW_START = datetime(2026, 9, 14, tzinfo=UTC)


def make_usage(input_tokens: int = 120, output_tokens: int = 30) -> Usage:
    """A `Usage` with the given counters."""
    return Usage(input_tokens=TokenCount(input_tokens), output_tokens=TokenCount(output_tokens))


def make_provider(name: str = "anthropic", *, enabled: bool = True) -> Provider:
    """A provider; an enabled one gets a secret reference, as the registry requires."""
    return Provider(
        name=ProviderName(name),
        enabled=enabled,
        api_key_ref=f"holahost/dev/llm-client/{name}-api-key" if enabled else None,
    )


def make_model(
    model_id: str = "claude-haiku-4-5",
    *,
    provider: Provider | None = None,
    max_context: int = 200_000,
    max_output: int = 8192,
    tokens_per_second: int = 100,
) -> Model:
    """A model of `provider` (anthropic by default)."""
    return Model(
        provider=provider if provider is not None else make_provider(),
        id=ModelId(model_id),
        max_context=max_context,
        max_output=max_output,
        price_in=Decimal("1"),
        price_out=Decimal("5"),
        tokens_per_second=tokens_per_second,
        deprecated=False,
    )


def make_budget(
    scope: BudgetScope,
    key: ClientId | ProviderName,
    *,
    spent: Usage | None = None,
    caps: Usage | None = None,
) -> Budget:
    """A budget for the current window; nothing spent by default."""
    return Budget(
        scope=scope,
        key=key,
        window_start=WINDOW_START,
        spent=spent if spent is not None else make_usage(0, 0),
        caps=caps if caps is not None else make_usage(2_000_000, 200_000),
    )


def exhausted_budget(scope: BudgetScope, key: ClientId | ProviderName) -> Budget:
    """A budget whose counters have reached their ceilings."""
    caps = make_usage(2_000_000, 200_000)
    return make_budget(scope, key, spent=caps, caps=caps)


def make_generation(
    *,
    text: str = "Check-in is from 15:00.",
    usage: Usage | None = None,
    finish_reason: FinishReason = FinishReason.STOP,
) -> Generation:
    """A provider's answer."""
    return Generation(
        text=text,
        usage=usage if usage is not None else make_usage(),
        finish_reason=finish_reason,
    )


def make_record(
    *,
    client_id: str = CLIENT,
    provider: str = "anthropic",
    usage: Usage | None = None,
    downgraded: bool = False,
    created_at: datetime | None = None,
) -> UsageRecord:
    """A usage record, created now unless told otherwise."""
    return UsageRecord(
        id=GenerationId.new(),
        request_id="req-1",
        client_id=ClientId(client_id),
        subject=Subject(client_id),
        provider=ProviderName(provider),
        model=ModelId("claude-haiku-4-5"),
        usage=usage if usage is not None else make_usage(),
        latency_ms=900,
        downgraded=downgraded,
        failed_over=False,
        created_at=created_at if created_at is not None else datetime.now(tz=UTC),
    )


def make_cmd(
    *,
    model_ref: str = "fast",
    system: str = "You answer guests.",
    messages: list[MessageInput] | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    stop: list[str] | None = None,
    idempotency_key: str | None = None,
    client_id: str = CLIENT,
    subject: str = CLIENT,
    request_id: str = "req-1",
) -> GenerateCmd:
    """A generation command; one user message by default."""
    return GenerateCmd(
        client_id=client_id,
        subject=subject,
        request_id=request_id,
        model_ref=model_ref,
        system=system,
        messages=(
            messages
            if messages is not None
            else [MessageInput(role="user", text="What time is check-in?")]
        ),
        max_tokens=max_tokens,
        temperature=temperature,
        stop=stop,
        idempotency_key=idempotency_key,
    )


ANTHROPIC = make_provider("anthropic")
OTHER_VENDOR = make_provider("other-vendor")
HAIKU = make_model("claude-haiku-4-5", provider=ANTHROPIC)
SONNET = make_model("claude-sonnet-4-6", provider=ANTHROPIC)
FALLBACK = make_model("other-vendor-mini", provider=OTHER_VENDOR)


__all__ = [
    "ANTHROPIC",
    "CLIENT",
    "FALLBACK",
    "HAIKU",
    "OTHER_VENDOR",
    "SONNET",
    "WINDOW_START",
    "exhausted_budget",
    "make_budget",
    "make_cmd",
    "make_generation",
    "make_model",
    "make_provider",
    "make_record",
    "make_usage",
]
