"""Request and response models for this service's routes.

The request models publish types, not ranges: the use case judges every field itself — it trusts
no command to have come through this schema — so a bound declared here too would answer one
fault with two different `details.field`s. The ranges are stated in the descriptions, where a
caller reads them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from application.dto.generation import GenerateResult, MessageInput
from application.limits import MAX_OUTPUT_TOKENS, MAX_STOP_SEQUENCES
from domain.value_objects.idempotency_key import MAX_IDEMPOTENCY_KEY_LENGTH


class _Request(BaseModel):
    # A misspelt optional field refused rather than ignored: ignored, it would serve the request
    # with the default the caller meant to change. Strict, so a type is enforced rather than
    # coerced — lax mode would serve `"temperature": true` as 1.0. An integer still passes for a
    # float.
    model_config = ConfigDict(extra="forbid", strict=True)


class MessageIn(_Request):
    role: str = Field(description="`user` — the only role in this version.")
    content: str = Field(description="The message text, passed to the provider unchanged.")

    def to_input(self) -> MessageInput:
        return MessageInput(role=self.role, text=self.content)


class GenerateRequest(_Request):
    model: str = Field(description="A model alias (`fast`, `quality`, `default`) or a model id.")
    system: str = Field(
        default="",
        description="The system instruction, passed to the provider unchanged; empty sends none.",
    )
    messages: list[MessageIn] = Field(description="The conversation, in order; at least one.")
    max_tokens: int | None = Field(
        default=None,
        description=(
            f"The answer's ceiling, at least 1. At most {MAX_OUTPUT_TOKENS}: a larger value is "
            "truncated to it. Absent means the model's own ceiling, capped the same way."
        ),
    )
    temperature: float | None = Field(default=None, description="From 0 to 1.")
    stop: list[str] | None = Field(
        default=None,
        description=f"Up to {MAX_STOP_SEQUENCES} stop sequences, none of them empty.",
    )


IDEMPOTENCY_KEY_DESCRIPTION = (
    f"1 to {MAX_IDEMPOTENCY_KEY_LENGTH} characters. A repeat with the same key within the key's "
    "lifetime is answered `409 DuplicateRequestError` instead of paying for a second generation; "
    "the first answer is not returned again."
)


class UsageOut(BaseModel):
    input_tokens: int
    output_tokens: int


class GenerateResponse(BaseModel):
    text: str
    usage: UsageOut
    provider: str = Field(description="The provider that answered.")
    model: str = Field(description="The model that answered — not always the one asked for.")
    finish_reason: Literal["stop", "max_tokens"]
    downgraded: bool = Field(description="The budget policy moved the request to a cheaper model.")
    failed_over: bool = Field(description="A candidate other than the first answered.")

    @classmethod
    def from_result(cls, result: GenerateResult) -> GenerateResponse:
        return cls(
            text=result.text,
            usage=UsageOut(input_tokens=result.input_tokens, output_tokens=result.output_tokens),
            provider=result.provider,
            model=result.model,
            # `str` in the result, a `Literal` here: validated on construction, so a stop reason
            # outside the enumeration is a defect rather than a published value.
            finish_reason=result.finish_reason,
            downgraded=result.downgraded,
            failed_over=result.failed_over,
        )


class HealthResponse(BaseModel):
    status: Literal["ok"]
