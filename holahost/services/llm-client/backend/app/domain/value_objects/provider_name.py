"""A provider's name."""

from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class ProviderName:
    """A provider's name in the registry.

    Whether the name is known is not this value's concern: an unknown name is a resolution
    failure, not an invalid value.

    :param value: The name.
    """

    value: str

    def __post_init__(self) -> None:
        # From the registry or a provider's response, never from a request — `field` stays None.
        if not self.value.strip():
            raise DomainValidationError("ProviderName must not be empty")
