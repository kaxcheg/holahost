"""Provider keys: one environment variable per enabled provider's secret reference."""

from __future__ import annotations

import pytest
from tests._support.registry import registry_data

from config.provider_keys import MissingProviderKeyError, key_variable, read_provider_keys
from config.registry import RegistryFile

_REGISTRY = RegistryFile.model_validate(registry_data())
_BOTH = {"ANTHROPIC_API_KEY": "sk-a", "OTHER_VENDOR_API_KEY": "sk-o"}


class TestTheVariable:
    def test_is_the_reference_upper_cased_with_underscores(self) -> None:
        assert key_variable("anthropic-api-key") == "ANTHROPIC_API_KEY"


class TestReading:
    def test_reads_every_enabled_providers_key(self) -> None:
        keys = read_provider_keys(_REGISTRY, _BOTH)
        assert {p: k.get_secret_value() for p, k in keys.items()} == {
            "anthropic": "sk-a",
            "other-vendor": "sk-o",
        }

    def test_a_key_stays_out_of_its_repr(self) -> None:
        assert "sk-a" not in repr(read_provider_keys(_REGISTRY, _BOTH))

    def test_a_missing_key_names_every_variable(self) -> None:
        with pytest.raises(
            MissingProviderKeyError, match="ANTHROPIC_API_KEY, OTHER_VENDOR_API_KEY"
        ):
            read_provider_keys(_REGISTRY, {})

    def test_a_blank_key_counts_as_missing(self) -> None:
        with pytest.raises(MissingProviderKeyError, match="OTHER_VENDOR_API_KEY"):
            read_provider_keys(_REGISTRY, {**_BOTH, "OTHER_VENDOR_API_KEY": "  "})

    def test_a_disabled_providers_key_is_not_asked_for(self) -> None:
        data = registry_data()
        data["providers"]["other-vendor"]["enabled"] = False
        keys = read_provider_keys(RegistryFile.model_validate(data), {"ANTHROPIC_API_KEY": "sk-a"})
        assert list(keys) == ["anthropic"]
