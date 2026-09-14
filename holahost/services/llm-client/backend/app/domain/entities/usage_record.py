"""The `UsageRecord` entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from domain.exceptions import DomainValidationError
from domain.value_objects.client_id import ClientId
from domain.value_objects.generation_id import GenerationId
from domain.value_objects.model_id import ModelId
from domain.value_objects.provider_name import ProviderName
from domain.value_objects.subject import Subject
from domain.value_objects.usage import Usage


@dataclass(frozen=True, eq=False)
class UsageRecord:
    """One confirmed successful provider call in the usage log.

    Immutable and append-only, created only from a provider's confirmed response, and it carries
    no request or response text. `provider` and `model` are the ones that answered, not the ones
    requested; `downgraded` and `failed_over` say why the two may differ.

    :param id: Self-generated, unique per generation.
    :param request_id: The request's `X-Request-ID`, for correlation with logs — not the identity
        (see `GenerationId`).
    :param client_id: The calling client.
    :param subject: The token's subject.
    :param provider: The provider that answered.
    :param model: The model that answered.
    :param usage: The provider's own figures, never an estimate.
    :param latency_ms: How long the provider call took; >= 0.
    :param downgraded: The budget policy moved the request to the cheaper model.
    :param failed_over: A provider other than the first in the chain answered.
    :param created_at: UTC, set at creation.
    """

    id: GenerationId
    request_id: str
    client_id: ClientId
    subject: Subject
    provider: ProviderName
    model: ModelId
    usage: Usage
    latency_ms: int
    downgraded: bool
    failed_over: bool
    created_at: datetime

    def __post_init__(self) -> None:
        # Measured by the use case, not sent by the caller — `field` stays None.
        if self.latency_ms < 0:
            raise DomainValidationError("UsageRecord latency_ms must not be negative")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, UsageRecord):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        client_id: ClientId,
        subject: Subject,
        provider: ProviderName,
        model: ModelId,
        usage: Usage,
        latency_ms: int,
        downgraded: bool,
        failed_over: bool,
    ) -> UsageRecord:
        """Record a confirmed call under a fresh identifier and the current time.

        :raises DomainValidationError: `latency_ms` is negative — with `field` unset, a defect.
        """
        return cls(
            id=GenerationId.new(),
            request_id=request_id,
            client_id=client_id,
            subject=subject,
            provider=provider,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            downgraded=downgraded,
            failed_over=failed_over,
            created_at=datetime.now(tz=UTC),
        )
