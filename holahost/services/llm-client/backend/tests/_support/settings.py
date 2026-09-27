"""The environment `Settings` reads, for the tests that build it."""

from __future__ import annotations

import pytest

SERVICE_ENV: dict[str, str] = {
    "BUDGET_CAP_CLIENT_INPUT_TOKENS": "2000000",
    "BUDGET_CAP_CLIENT_OUTPUT_TOKENS": "200000",
    "BUDGET_CAP_CLIENT_DOWNGRADE_INPUT_TOKENS": "200000",
    "BUDGET_CAP_CLIENT_DOWNGRADE_OUTPUT_TOKENS": "20000",
    "BUDGET_CAP_PROVIDER_INPUT_TOKENS": "10000000",
    "BUDGET_CAP_PROVIDER_OUTPUT_TOKENS": "1000000",
    "IDEMPOTENCY_KEY_TTL_SECONDS": "900",
    "RATE_LIMIT_USER_GENERATE": "60",
    "RATE_LIMIT_SERVICE_GENERATE": "600",
}
"""The service's own variables — what `infra/envs/dev/.env.example` sets beyond the Postgres
identity."""

SETTINGS_ENV: dict[str, str] = {
    "ENV": "dev",
    "POSTGRES_USER": "user",
    "POSTGRES_PASSWORD": "pass",
    "POSTGRES_DB": "llm_client",
    **SERVICE_ENV,
}


def set_settings_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    """Set everything `Settings` requires, with `overrides` on top."""
    for key, value in {**SETTINGS_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
