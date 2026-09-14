"""A model's identifier at its provider."""

from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class ModelId:
    """A model's identifier at its provider, as the provider's API names it.

    :param value: The identifier.
    """

    value: str

    def __post_init__(self) -> None:
        # From the registry or a provider's response — `field` stays None.
        if not self.value.strip():
            raise DomainValidationError("ModelId must not be empty")
