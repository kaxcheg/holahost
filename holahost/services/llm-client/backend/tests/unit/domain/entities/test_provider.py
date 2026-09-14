import dataclasses

import pytest

from domain.entities.provider import Provider
from domain.exceptions import DomainValidationError
from domain.value_objects.provider_name import ProviderName

_KEY_REF = "holahost/dev/llm-client/anthropic-api-key"


def _provider(name: str = "anthropic", *, enabled: bool = True) -> Provider:
    return Provider(name=ProviderName(name), enabled=enabled, api_key_ref=_KEY_REF)


class TestProvider:
    def test_holds_fields(self) -> None:
        provider = _provider()
        assert provider.name == ProviderName("anthropic")
        assert provider.enabled is True
        assert provider.api_key_ref == _KEY_REF

    def test_rejects_an_enabled_provider_without_a_key_ref(self) -> None:
        with pytest.raises(DomainValidationError, match="api_key_ref") as exc:
            Provider(name=ProviderName("anthropic"), enabled=True, api_key_ref=None)
        assert exc.value.field is None

    def test_rejects_an_enabled_provider_with_a_blank_key_ref(self) -> None:
        with pytest.raises(DomainValidationError, match="api_key_ref") as exc:
            Provider(name=ProviderName("anthropic"), enabled=True, api_key_ref="  ")
        assert exc.value.field is None

    def test_accepts_a_disabled_provider_without_a_key_ref(self) -> None:
        provider = Provider(name=ProviderName("openai"), enabled=False, api_key_ref=None)
        assert provider.api_key_ref is None

    def test_is_immutable(self) -> None:
        provider = _provider()
        with pytest.raises(dataclasses.FrozenInstanceError):
            provider.enabled = False  # type: ignore[misc]

    def test_equal_when_same_name_regardless_of_other_fields(self) -> None:
        disabled = Provider(name=ProviderName("anthropic"), enabled=False, api_key_ref=None)
        assert _provider() == disabled

    def test_not_equal_when_different_name_or_other_type(self) -> None:
        assert _provider("anthropic") != _provider("openai")
        assert _provider() != object()

    def test_hashable_by_name(self) -> None:
        disabled = Provider(name=ProviderName("anthropic"), enabled=False, api_key_ref=None)
        assert hash(_provider()) == hash(disabled)
        assert len({_provider(), disabled}) == 1
