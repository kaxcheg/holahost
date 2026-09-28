"""`llm-client`: one generation.

The tool names an alias, never a vendor model: which model answers, the retries, failover and the
budget are the service's. The answer says which provider and model actually answered.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from guest_reply.clients.http import ServiceCaller

API_BASE = "/api/llm-client"

GENERATE_READ_TIMEOUT = 35.0
"""Seconds: a little over the service's synchronous ceiling, so that its own error reaches the
operator rather than a client-side cut-off."""


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    content: str


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int
    output_tokens: int


class Generated(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    usage: Usage
    provider: str
    model: str


class GenerationClient:
    """The generation service; raises what `ServiceCaller` does."""

    def __init__(self, caller: ServiceCaller) -> None:
        self._caller = caller

    def generate(self, *, system: str, messages: list[Message], model: str) -> Generated:
        """One generation from a system prompt and a conversation, on the model alias `model`.

        :raises ProviderUnavailableError: no provider answered; the service already retried.
        :raises LimitReachedError: the rate limit, or the client's token budget.
        :raises RequestRejectedError: an unknown alias, a context too large, content refused.
        """
        return self._caller.fetch(
            Generated,
            "POST",
            "/generate",
            read_timeout=GENERATE_READ_TIMEOUT,
            json={
                "model": model,
                "system": system,
                "messages": [message.model_dump() for message in messages],
            },
        )
