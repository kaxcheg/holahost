"""`ProvidersRepo` over the registry file.

The domain objects are built once, when the process starts, and never change afterwards — a change
is a rollout — so every method reads them without a lock, and none of them can fail.
"""

from __future__ import annotations

from collections.abc import Mapping

from application.estimates import generation_seconds, output_ceiling
from application.limits import PROVIDER_TIMEOUT_SECONDS
from config.registry import ModelRef, RegistryFile
from domain.entities.model import Model
from domain.entities.provider import Provider
from domain.exceptions import DomainValidationError
from domain.value_objects.model_id import ModelId
from domain.value_objects.provider_name import ProviderName


class InvalidRegistryError(ValueError):
    """The registry breaks a rule no request could: the service must not start on it."""


class ConfigProvidersRepo:
    """The registry's models by alias and by identifier, with disabled providers' left out."""

    def __init__(
        self,
        *,
        aliases: Mapping[str, list[Model]],
        models: Mapping[str, Model],
        downgrade_targets: list[Model],
    ) -> None:
        self._aliases = {alias: _enabled(chain) for alias, chain in aliases.items()}
        self._models = {
            model_id: model for model_id, model in models.items() if model.provider.enabled
        }
        self._downgrade_targets = _enabled(downgrade_targets)

    def resolve(self, model_ref: str) -> list[Model]:
        if model_ref in self._aliases:
            return list(self._aliases[model_ref])
        model = self._models.get(model_ref)
        return [model] if model is not None else []

    def downgrade_targets(self) -> list[Model]:
        return list(self._downgrade_targets)

    def aliases(self) -> list[str]:
        return sorted(alias for alias, chain in self._aliases.items() if chain)


def load_providers_repo(registry: RegistryFile) -> ConfigProvidersRepo:
    """Build the registry's domain objects and check what only they can settle.

    The same procedure serves startup and CI's config validation, so a registry passing one passes
    the other.

    :raises InvalidRegistryError: a provider or model breaks its entity's invariant, or a model
        cannot deliver its answer ceiling within one attempt — then every request sending no
        `max_tokens` would be refused before any call.
    """
    models: dict[str, Model] = {}
    for name, entry in registry.providers.items():
        try:
            provider = Provider(
                name=ProviderName(name), enabled=entry.enabled, api_key_ref=entry.api_key_ref
            )
        except DomainValidationError as error:
            raise InvalidRegistryError(f"provider {name!r}: {error}") from error
        for model_id, spec in entry.models.items():
            try:
                models[model_id] = Model(
                    provider=provider,
                    id=ModelId(model_id),
                    max_context=spec.max_context,
                    max_output=spec.max_output,
                    price_in=spec.price_in,
                    price_out=spec.price_out,
                    tokens_per_second=spec.tokens_per_second,
                    deprecated=spec.deprecated,
                )
            except DomainValidationError as error:
                raise InvalidRegistryError(f"model {name}/{model_id}: {error}") from error

    too_slow = [
        f"{model.provider.name.value}/{model_id}"
        for model_id, model in models.items()
        if generation_seconds(output_ceiling(model), model) > PROVIDER_TIMEOUT_SECONDS
    ]
    if too_slow:
        raise InvalidRegistryError(
            f"cannot deliver the answer ceiling within one {PROVIDER_TIMEOUT_SECONDS:g} s attempt: "
            + ", ".join(too_slow)
        )

    def chain(refs: list[ModelRef]) -> list[Model]:
        return [models[ref.model] for ref in refs]

    return ConfigProvidersRepo(
        aliases={alias: chain(refs) for alias, refs in registry.aliases.items()},
        models=models,
        downgrade_targets=chain(registry.downgrade_targets),
    )


def _enabled(models: list[Model]) -> list[Model]:
    return [model for model in models if model.provider.enabled]
