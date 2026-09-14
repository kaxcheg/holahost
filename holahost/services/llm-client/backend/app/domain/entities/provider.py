"""The `Provider` entity."""

from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainValidationError
from domain.value_objects.provider_name import ProviderName


@dataclass(frozen=True, eq=False)
class Provider:
    """An external LLM provider from the registry.

    Frozen: the registry is loaded and validated at startup and changes only with a rollout.
    Identified by `name` — a provider switched off in config is still the same provider.

    Holds no models. `Model` refers to its provider, and a reference back would make the two
    impossible to build frozen; "an enabled provider has at least one model" is a property of the
    whole registry, checked where the registry is loaded.

    :param name: The provider's name.
    :param enabled: A disabled provider takes part in neither model resolution nor failover.
    :param api_key_ref: The secret's name in the secret store, never its value; may be absent only
        for a disabled provider.
    """

    name: ProviderName
    enabled: bool
    api_key_ref: str | None

    def __post_init__(self) -> None:
        # Registry configuration: a violation keeps the service from starting, so `field` stays
        # None.
        if self.enabled and (self.api_key_ref is None or not self.api_key_ref.strip()):
            raise DomainValidationError("An enabled Provider must have an api_key_ref")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Provider):
            return NotImplemented
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)
