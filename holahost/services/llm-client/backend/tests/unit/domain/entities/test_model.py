import dataclasses
from decimal import Decimal

import pytest

from domain.entities.model import Model
from domain.entities.provider import Provider
from domain.exceptions import DomainValidationError
from domain.value_objects.model_id import ModelId
from domain.value_objects.provider_name import ProviderName

_ANTHROPIC = Provider(
    name=ProviderName("anthropic"),
    enabled=True,
    api_key_ref="holahost/dev/llm-client/anthropic-api-key",
)
_OTHER = Provider(name=ProviderName("other"), enabled=False, api_key_ref=None)


def _model(
    *,
    provider: Provider = _ANTHROPIC,
    model_id: str = "claude-haiku-4-5",
    max_context: int = 200_000,
    max_output: int = 8192,
    tokens_per_second: int = 50,
    deprecated: bool = False,
) -> Model:
    return Model(
        provider=provider,
        id=ModelId(model_id),
        max_context=max_context,
        max_output=max_output,
        price_in=Decimal("1.00"),
        price_out=Decimal("5.00"),
        tokens_per_second=tokens_per_second,
        deprecated=deprecated,
    )


class TestModel:
    def test_holds_fields(self) -> None:
        model = _model()
        assert model.provider is _ANTHROPIC
        assert model.id == ModelId("claude-haiku-4-5")
        assert model.max_context == 200_000
        assert model.max_output == 8192
        assert model.price_in == Decimal("1.00")
        assert model.price_out == Decimal("5.00")
        assert model.tokens_per_second == 50
        assert model.deprecated is False

    def test_rejects_a_non_positive_max_output(self) -> None:
        with pytest.raises(DomainValidationError, match="max_output") as exc:
            _model(max_output=0)
        assert exc.value.field is None

    def test_rejects_max_context_not_exceeding_max_output(self) -> None:
        with pytest.raises(DomainValidationError, match="max_context") as exc:
            _model(max_context=8192, max_output=8192)
        assert exc.value.field is None

    def test_rejects_a_non_positive_tokens_per_second(self) -> None:
        with pytest.raises(DomainValidationError, match="tokens_per_second") as exc:
            _model(tokens_per_second=0)
        assert exc.value.field is None

    def test_is_immutable(self) -> None:
        model = _model()
        with pytest.raises(dataclasses.FrozenInstanceError):
            model.deprecated = True  # type: ignore[misc]

    def test_equal_when_same_provider_and_id_regardless_of_other_fields(self) -> None:
        assert _model() == _model(max_output=1000, tokens_per_second=10, deprecated=True)

    def test_not_equal_when_same_id_at_another_provider(self) -> None:
        assert _model() != _model(provider=_OTHER)

    def test_not_equal_when_different_id_or_other_type(self) -> None:
        assert _model() != _model(model_id="claude-sonnet-4-6")
        assert _model() != object()

    def test_hashable_by_provider_and_id(self) -> None:
        a = _model()
        b = _model(deprecated=True)
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
