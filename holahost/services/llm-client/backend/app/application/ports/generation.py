"""Port for calling a model, and the answer it returns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from domain.entities.model import Model
from domain.value_objects.finish_reason import FinishReason
from domain.value_objects.message import Message
from domain.value_objects.usage import Usage


@dataclass(frozen=True, slots=True)
class Generation:
    """What a model answered — exists only inside one call and is stored nowhere.

    Carries neither provider nor model: the answer comes from the model the call named, which the
    caller already holds. A second copy would be a second source for the same fact, and a vendor's
    own model string (a dated version) is not the registry's identifier anyway.

    :param text: The answer.
    :param usage: The provider's own figures, never an estimate.
    :param finish_reason: Why generation stopped.
    """

    text: str
    usage: Usage
    finish_reason: FinishReason


class GenerationProvider(Protocol):
    """Calls a model at its provider and answers in this port's terms.

    Everything vendor-specific stays in the adapter: its errors, its stop reasons, how it takes a
    system instruction. The adapter repeats nothing and chooses no model — retries, failover and the
    budget are the use case's.

    Concurrency: implementations must be thread-safe. One instance serves the whole process and is
    called concurrently from the request thread pool.
    """

    def generate(
        self,
        model: Model,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int,
        temperature: float | None,
        stop: list[str] | None,
        timeout_s: float,
        request_id: str,
    ) -> Generation:
        """Generate one answer.

        :param model: The model to call; its provider says which vendor.
        :param system: The system instruction, passed as the vendor's own and never merged into
            `messages`.
        :param messages: Passed in order and unchanged.
        :param max_tokens: The ceiling on the answer.
        :param temperature: Left out of the vendor call when `None`.
        :param stop: Left out of the vendor call when `None`.
        :param timeout_s: The wait for the answer — the time pre-flight measured the generation
            against; running past it is a transient failure. Setting up the call is bounded apart,
            briefly, by the adapter.
        :param request_id: The request's `X-Request-ID`, propagated to the vendor where its protocol
            allows.
        :return: The answer.
        :raises TransientProviderError: `429`, a `5xx`, overload or the timeout — worth repeating.
        :raises ProviderRejectedRequestError: the vendor refused the request itself — not worth
            repeating at this vendor.
        :raises ProviderRefusedContentError: the model declined this content; carries the usage.
        """
        ...
