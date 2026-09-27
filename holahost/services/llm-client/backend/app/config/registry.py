"""The registry of providers, models and aliases, as `registry.yaml` states it.

Configuration in the service's repository rather than rows in its database: a change is reviewed,
lands in history, and is applied by a rollout. It is read once, at startup, and an error
in it stops the process there instead of surfacing on the first request that meets it. Every rule
the file alone can settle is checked here, in one pass that reports them all; what only the domain
objects can settle — their own invariants, and whether a model can deliver its answer ceiling in
one attempt — is checked where they are built (`infrastructure/registry`).

Primitives only: `config` is the leaf every layer imports, and it imports none of them.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REGISTRY_PATH = Path(__file__).with_name("registry.yaml")

Policy = Literal["reject", "downgrade"]


class _Entry(BaseModel):
    # `forbid`: a misspelt key is an error, not a setting silently left at its default.
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelEntry(_Entry):
    max_context: int
    max_output: int
    price_in: Decimal
    price_out: Decimal
    tokens_per_second: int
    deprecated: bool = False


class ProviderEntry(_Entry):
    enabled: bool
    # Kebab-case: the environment variable the key is read from is derived from it
    # (`provider_keys.key_variable`), and has to be a name an env file can set.
    api_key_ref: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
    models: dict[str, ModelEntry]


class ModelRef(_Entry):
    provider: str
    model: str


class BudgetPolicies(_Entry):
    """What a caller's own exhausted budget leads to: a default, overridden per `client_id`."""

    default: Policy
    overrides: dict[str, Policy] = Field(default_factory=dict)


class RegistryFile(_Entry):
    providers: dict[str, ProviderEntry]
    aliases: dict[str, list[ModelRef]]
    downgrade_targets: list[ModelRef] = Field(default_factory=list)
    on_budget_exhausted: BudgetPolicies

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        problems = [*self._alias_problems(), *self._target_problems(), *self._provider_problems()]
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def enabled_key_refs(self) -> dict[str, str]:
        """The secret reference of every enabled provider, by provider name.

        An enabled provider without one is left out rather than refused: that is the `Provider`
        entity's invariant, reported where the entity is built.
        """
        return {
            name: entry.api_key_ref
            for name, entry in self.providers.items()
            if entry.enabled and entry.api_key_ref is not None
        }

    def _model(self, ref: ModelRef) -> ModelEntry | None:
        provider = self.providers.get(ref.provider)
        return provider.models.get(ref.model) if provider is not None else None

    def _alias_problems(self) -> list[str]:
        model_ids = {model_id for entry in self.providers.values() for model_id in entry.models}
        problems: list[str] = []
        for alias, chain in self.aliases.items():
            if not chain:
                problems.append(f"alias {alias!r} has no candidates")
            if alias in model_ids:
                # A request names either; one string meaning both would resolve by accident.
                problems.append(f"alias {alias!r} is also a model id")
            if len(set(chain)) < len(chain):
                # The repeat would be a "failover" to the model that has just failed.
                problems.append(f"alias {alias!r} lists a model more than once")
            for ref in chain:
                model = self._model(ref)
                if model is None:
                    problems.append(
                        f"alias {alias!r} points at unknown model {ref.provider}/{ref.model}"
                    )
                elif model.deprecated:
                    problems.append(
                        f"alias {alias!r} points at deprecated model {ref.provider}/{ref.model}"
                    )
        return problems

    def _target_problems(self) -> list[str]:
        problems = [
            f"downgrade target points at unknown model {ref.provider}/{ref.model}"
            for ref in self.downgrade_targets
            if self._model(ref) is None
        ]
        if len(set(self.downgrade_targets)) < len(self.downgrade_targets):
            problems.append("a downgrade target listed more than once")
        return problems

    def _provider_problems(self) -> list[str]:
        problems = [
            f"enabled provider {name!r} has no models"
            for name, entry in self.providers.items()
            if entry.enabled and not entry.models
        ]
        owners = Counter(model_id for entry in self.providers.values() for model_id in entry.models)
        problems += [
            f"model id {model_id!r} belongs to more than one provider"
            for model_id, count in owners.items()
            if count > 1
        ]
        return problems


def read_registry(path: Path = REGISTRY_PATH) -> RegistryFile:
    """Parse and check the registry file.

    :raises OSError: the file cannot be read.
    :raises yaml.YAMLError: it is not YAML.
    :raises pydantic.ValidationError: its shape, or a reference in it, is wrong.
    """
    with path.open(encoding="utf-8") as handle:
        return RegistryFile.model_validate(yaml.safe_load(handle))
