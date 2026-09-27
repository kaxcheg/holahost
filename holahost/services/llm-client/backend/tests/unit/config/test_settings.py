"""`Settings`: the service's own variables on top of the Postgres identity."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tests._support.settings import SERVICE_ENV, set_settings_env

from config.settings import Settings


class TestSettings:
    def test_reads_the_services_own_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_settings_env(monkeypatch)

        settings = Settings.from_env()

        assert (
            settings.budget_cap_client_input_tokens,
            settings.budget_cap_client_output_tokens,
        ) == (2_000_000, 200_000)
        assert (
            settings.budget_cap_client_downgrade_input_tokens,
            settings.budget_cap_client_downgrade_output_tokens,
        ) == (200_000, 20_000)
        assert (
            settings.budget_cap_provider_input_tokens,
            settings.budget_cap_provider_output_tokens,
        ) == (10_000_000, 1_000_000)
        assert settings.idempotency_key_ttl_seconds == 900
        assert (settings.rate_limit_user_generate, settings.rate_limit_service_generate) == (
            60,
            600,
        )

    @pytest.mark.parametrize("variable", sorted(SERVICE_ENV))
    def test_every_one_is_required(self, monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
        set_settings_env(monkeypatch)
        monkeypatch.delenv(variable)
        with pytest.raises(ValidationError):
            Settings.from_env()

    @pytest.mark.parametrize("variable", sorted(SERVICE_ENV))
    def test_every_one_is_positive(self, monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
        set_settings_env(monkeypatch, **{variable: "0"})
        with pytest.raises(ValidationError):
            Settings.from_env()
