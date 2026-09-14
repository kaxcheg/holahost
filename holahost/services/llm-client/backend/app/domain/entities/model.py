"""The `Model` entity."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from domain.entities.provider import Provider
from domain.exceptions import DomainValidationError
from domain.value_objects.model_id import ModelId


@dataclass(frozen=True, eq=False)
class Model:
    """A provider's model from the registry.

    Holds its provider as the object itself, so resolving a model also yields its provider and no
    separate "permitted provider + model pair" type is needed. Frozen for the same reason as
    `Provider`; identified by `(provider name, id)`.

    :param provider: The provider serving this model.
    :param id: The model's identifier at the provider.
    :param max_context: The context window, in tokens.
    :param max_output: The model's own ceiling on an answer, in tokens.
    :param price_in: Price per 1M input tokens — kept for reporting, used in no calculation.
    :param price_out: Price per 1M output tokens — likewise.
    :param tokens_per_second: A conservative generation speed; the pre-flight estimate divides by
        it.
    :param deprecated: A deprecated model still resolves; no new alias may point at it.
    """

    provider: Provider
    id: ModelId
    max_context: int
    max_output: int
    price_in: Decimal
    price_out: Decimal
    tokens_per_second: int
    deprecated: bool

    def __post_init__(self) -> None:
        # Registry configuration: a violation keeps the service from starting — `field` stays
        # None.
        if self.max_output <= 0:
            raise DomainValidationError("Model max_output must be positive")
        if self.max_context <= self.max_output:
            raise DomainValidationError("Model max_context must exceed max_output")
        if self.tokens_per_second <= 0:
            raise DomainValidationError("Model tokens_per_second must be positive")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Model):
            return NotImplemented
        return (self.provider.name, self.id) == (other.provider.name, other.id)

    def __hash__(self) -> int:
        return hash((self.provider.name, self.id))
