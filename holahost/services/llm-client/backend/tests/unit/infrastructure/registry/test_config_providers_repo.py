"""`ConfigProvidersRepo`, and the checks only the registry's domain objects can make."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from tests._support.registry import model_entry, ref, registry_data

from config.registry import RegistryFile, read_registry
from domain.entities.model import Model
from infrastructure.providers.dialects import DIALECTS
from infrastructure.registry.config_providers_repo import (
    ConfigProvidersRepo,
    InvalidRegistryError,
    load_providers_repo,
)


def _load(data: dict[str, Any]) -> ConfigProvidersRepo:
    return load_providers_repo(
        RegistryFile.model_validate(data), supported={"anthropic", "other-vendor"}
    )


def _ids(models: list[Model]) -> list[str]:
    return [model.id.value for model in models]


class TestResolving:
    def test_an_alias_resolves_to_its_chain_in_order(self) -> None:
        assert _ids(_load(registry_data()).resolve("fast")) == [
            "claude-haiku-4-5",
            "other-vendor-mini",
        ]

    def test_a_model_id_resolves_to_that_model_alone(self) -> None:
        [model] = _load(registry_data()).resolve("other-vendor-mini")
        assert model.provider.name.value == "other-vendor"

    def test_an_unknown_reference_resolves_to_nothing(self) -> None:
        assert _load(registry_data()).resolve("huge") == []

    def test_a_disabled_providers_models_are_left_out(self) -> None:
        data = registry_data()
        data["providers"]["other-vendor"]["enabled"] = False
        repo = _load(data)
        assert _ids(repo.resolve("fast")) == ["claude-haiku-4-5"]
        assert repo.resolve("other-vendor-mini") == []

    def test_an_alias_left_without_models_is_not_offered(self) -> None:
        data = registry_data()
        data["providers"]["other-vendor"]["enabled"] = False
        data["aliases"]["cheap"] = [ref("other-vendor", "other-vendor-mini")]
        repo = _load(data)
        assert repo.resolve("cheap") == []
        assert repo.aliases() == ["fast", "quality"]

    def test_downgrade_targets_keep_their_order_without_disabled_ones(self) -> None:
        data = registry_data()
        data["downgrade_targets"] = [
            ref("other-vendor", "other-vendor-mini"),
            ref("anthropic", "claude-haiku-4-5"),
        ]
        assert _ids(_load(data).downgrade_targets()) == ["other-vendor-mini", "claude-haiku-4-5"]
        data["providers"]["other-vendor"]["enabled"] = False
        assert _ids(_load(data).downgrade_targets()) == ["claude-haiku-4-5"]

    def test_a_model_carries_the_registrys_figures(self) -> None:
        [model] = _load(registry_data()).resolve("quality")
        assert (model.max_context, model.max_output, model.tokens_per_second) == (200_000, 8192, 60)
        assert (model.price_in, model.price_out, model.deprecated) == (
            Decimal(1),
            Decimal(5),
            False,
        )
        assert model.provider.api_key_ref == "anthropic-api-key"


class TestTheDomainsChecks:
    def test_a_model_breaking_its_invariant_stops_the_load(self) -> None:
        data = registry_data()
        data["providers"]["anthropic"]["models"]["claude-haiku-4-5"] = model_entry(
            max_context=8192, max_output=8192
        )
        with pytest.raises(InvalidRegistryError, match="anthropic/claude-haiku-4-5"):
            _load(data)

    def test_an_enabled_provider_without_a_key_reference_stops_the_load(self) -> None:
        data = registry_data()
        del data["providers"]["anthropic"]["api_key_ref"]
        with pytest.raises(InvalidRegistryError, match="provider 'anthropic'"):
            _load(data)

    def test_a_model_too_slow_for_one_attempt_stops_the_load(self) -> None:
        # 1000 tokens at 40 tokens/s take 25 s, past the 20 s attempt: every request sending no
        # `max_tokens` would be refused before any call.
        data = registry_data()
        data["providers"]["anthropic"]["models"]["claude-haiku-4-5"] = model_entry(
            tokens_per_second=40
        )
        with pytest.raises(InvalidRegistryError, match="anthropic/claude-haiku-4-5"):
            _load(data)

    def test_a_models_own_lower_ceiling_is_what_has_to_fit(self) -> None:
        # 500 tokens at 30 tokens/s take under 17 s.
        data = registry_data()
        data["providers"]["anthropic"]["models"]["claude-haiku-4-5"] = model_entry(
            max_output=500, tokens_per_second=30
        )
        assert _load(data).resolve("fast")[0].max_output == 500


class TestAdapters:
    def test_an_enabled_provider_without_an_adapter_stops_the_load(self) -> None:
        with pytest.raises(
            InvalidRegistryError, match="no adapter for enabled provider: other-vendor"
        ):
            load_providers_repo(
                RegistryFile.model_validate(registry_data()), supported={"anthropic"}
            )

    def test_a_disabled_one_needs_none(self) -> None:
        data = registry_data()
        data["providers"]["other-vendor"]["enabled"] = False
        load_providers_repo(RegistryFile.model_validate(data), supported={"anthropic"})


class TestTheShippedRegistry:
    def test_it_loads(self) -> None:
        assert load_providers_repo(read_registry(), supported=DIALECTS).resolve("default")
