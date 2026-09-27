"""The registry file: its shape, and every rule the file alone can settle."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from tests._support.registry import model_entry, ref, registry_data

from config.registry import REGISTRY_PATH, RegistryFile, read_registry


class TestTheShape:
    def test_a_valid_registry_is_read(self) -> None:
        registry = RegistryFile.model_validate(registry_data())
        assert [r.model for r in registry.aliases["fast"]] == [
            "claude-haiku-4-5",
            "other-vendor-mini",
        ]
        assert registry.on_budget_exhausted.default == "reject"

    def test_a_model_is_not_deprecated_unless_marked(self) -> None:
        data = registry_data()
        del data["providers"]["anthropic"]["models"]["claude-haiku-4-5"]["deprecated"]
        registry = RegistryFile.model_validate(data)
        assert registry.providers["anthropic"].models["claude-haiku-4-5"].deprecated is False

    def test_a_misspelt_key_is_refused(self) -> None:
        data = registry_data()
        data["providers"]["anthropic"]["enabeld"] = True
        with pytest.raises(ValidationError, match="enabeld"):
            RegistryFile.model_validate(data)

    def test_an_unknown_policy_is_refused(self) -> None:
        data = registry_data()
        data["on_budget_exhausted"]["default"] = "ignore"
        with pytest.raises(ValidationError):
            RegistryFile.model_validate(data)


class TestReferences:
    def test_an_alias_to_an_unknown_model_is_refused(self) -> None:
        data = registry_data()
        data["aliases"]["fast"] = [ref("anthropic", "claude-nope")]
        with pytest.raises(ValidationError, match="alias 'fast' points at unknown model"):
            RegistryFile.model_validate(data)

    def test_a_model_under_the_wrong_provider_is_unknown(self) -> None:
        data = registry_data()
        data["aliases"]["fast"] = [ref("other-vendor", "claude-haiku-4-5")]
        with pytest.raises(ValidationError, match="unknown model other-vendor/claude-haiku-4-5"):
            RegistryFile.model_validate(data)

    def test_an_alias_with_no_candidates_is_refused(self) -> None:
        data = registry_data()
        data["aliases"]["fast"] = []
        with pytest.raises(ValidationError, match="alias 'fast' has no candidates"):
            RegistryFile.model_validate(data)

    def test_an_alias_to_a_deprecated_model_is_refused(self) -> None:
        data = registry_data()
        data["providers"]["anthropic"]["models"]["claude-sonnet-4-6"]["deprecated"] = True
        with pytest.raises(ValidationError, match="alias 'quality' points at deprecated model"):
            RegistryFile.model_validate(data)

    def test_a_deprecated_model_may_stay_a_downgrade_target(self) -> None:
        data = registry_data()
        data["providers"]["anthropic"]["models"]["claude-sonnet-4-6"]["deprecated"] = True
        del data["aliases"]["quality"]
        data["downgrade_targets"] = [ref("anthropic", "claude-sonnet-4-6")]
        RegistryFile.model_validate(data)

    def test_an_unknown_downgrade_target_is_refused(self) -> None:
        data = registry_data()
        data["downgrade_targets"] = [ref("anthropic", "claude-nope")]
        with pytest.raises(ValidationError, match="downgrade target points at unknown model"):
            RegistryFile.model_validate(data)

    def test_an_alias_named_like_a_model_is_refused(self) -> None:
        data = registry_data()
        data["aliases"]["other-vendor-mini"] = [ref("other-vendor", "other-vendor-mini")]
        with pytest.raises(ValidationError, match="alias 'other-vendor-mini' is also a model id"):
            RegistryFile.model_validate(data)

    def test_a_model_twice_in_one_chain_is_refused(self) -> None:
        # The second entry would be a "failover" to the model that has just failed.
        data = registry_data()
        data["aliases"]["fast"] = [ref("anthropic", "claude-haiku-4-5")] * 2
        with pytest.raises(ValidationError, match="alias 'fast' lists a model more than once"):
            RegistryFile.model_validate(data)

    def test_a_downgrade_target_listed_twice_is_refused(self) -> None:
        data = registry_data()
        data["downgrade_targets"] = [ref("anthropic", "claude-haiku-4-5")] * 2
        with pytest.raises(ValidationError, match="downgrade target listed more than once"):
            RegistryFile.model_validate(data)


class TestProviders:
    @pytest.mark.parametrize("key_ref", ["anthropic.api-key", "Anthropic-api-key", "1-key", ""])
    def test_a_key_reference_outside_kebab_case_is_refused(self, key_ref: str) -> None:
        # The environment variable the key is read from is derived from it, and has to be a name
        # an env file can set.
        data = registry_data()
        data["providers"]["anthropic"]["api_key_ref"] = key_ref
        with pytest.raises(ValidationError, match="api_key_ref"):
            RegistryFile.model_validate(data)

    def test_an_enabled_provider_without_models_is_refused(self) -> None:
        data = registry_data()
        data["providers"]["third"] = {"enabled": True, "api_key_ref": "third-api-key", "models": {}}
        with pytest.raises(ValidationError, match="enabled provider 'third' has no models"):
            RegistryFile.model_validate(data)

    def test_a_disabled_provider_may_have_no_models(self) -> None:
        data = registry_data()
        data["providers"]["third"] = {"enabled": False, "models": {}}
        RegistryFile.model_validate(data)

    def test_a_model_id_of_two_providers_is_refused(self) -> None:
        data = registry_data()
        data["providers"]["third"] = {
            "enabled": False,
            "models": {"claude-haiku-4-5": model_entry()},
        }
        with pytest.raises(
            ValidationError, match="'claude-haiku-4-5' belongs to more than one provider"
        ):
            RegistryFile.model_validate(data)

    def test_every_problem_is_reported_at_once(self) -> None:
        data = registry_data()
        data["aliases"]["fast"] = []
        data["downgrade_targets"] = [ref("anthropic", "claude-nope")]
        with pytest.raises(ValidationError) as exc:
            RegistryFile.model_validate(data)
        assert "no candidates" in str(exc.value)
        assert "downgrade target points at unknown model" in str(exc.value)


class TestKeyReferences:
    def test_only_enabled_providers_are_asked_for_a_key(self) -> None:
        data = registry_data()
        data["providers"]["other-vendor"]["enabled"] = False
        registry = RegistryFile.model_validate(data)
        assert registry.enabled_key_refs() == {"anthropic": "anthropic-api-key"}

    def test_a_provider_without_a_reference_is_left_to_the_entity(self) -> None:
        data = registry_data()
        del data["providers"]["anthropic"]["api_key_ref"]
        registry = RegistryFile.model_validate(data)
        assert registry.enabled_key_refs() == {"other-vendor": "other-vendor-api-key"}


class TestReading:
    def test_reads_a_file(self, tmp_path: Path) -> None:
        path = tmp_path / "registry.yaml"
        path.write_text(yaml.safe_dump(registry_data()), encoding="utf-8")
        assert read_registry(path).aliases.keys() == {"fast", "quality"}

    def test_a_file_that_is_not_yaml_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "registry.yaml"
        path.write_text("providers: [\n", encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            read_registry(path)

    def test_the_shipped_registry_is_valid(self) -> None:
        assert "default" in read_registry(REGISTRY_PATH).aliases
