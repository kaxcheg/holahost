"""The composition root's getters for this service's own configuration."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from holahost_http import RateLimitExceededError
from tests._support.builders import make_usage
from tests._support.settings import set_settings_env

from application.exceptions import DuplicateRequestError
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from domain.value_objects.idempotency_key import IdempotencyKey
from interface.http import dependencies
from interface.http.edge import GENERATE_BUCKET

_GETTERS = (
    dependencies.get_settings,
    dependencies.get_registry,
    dependencies.get_providers_repo,
    dependencies.get_provider_keys,
    dependencies.get_budget_caps,
    dependencies.get_rate_limiter,
    dependencies.get_idempotency_store,
)


@pytest.fixture(autouse=True)
def _fresh_singletons() -> Iterator[None]:
    for getter in _GETTERS:
        getter.cache_clear()
    yield
    for getter in _GETTERS:
        getter.cache_clear()


class TestBudgetCaps:
    def test_each_scope_gets_its_own_pair(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_settings_env(monkeypatch)
        assert dependencies.get_budget_caps() == {
            BudgetScope.CLIENT: make_usage(2_000_000, 200_000),
            BudgetScope.CLIENT_DOWNGRADE: make_usage(200_000, 20_000),
            BudgetScope.PROVIDER: make_usage(10_000_000, 1_000_000),
        }


class TestTheIdempotencyStore:
    def test_is_one_store_for_the_whole_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_settings_env(monkeypatch)
        dependencies.get_idempotency_store().begin(ClientId("cli"), IdempotencyKey("k-1"))
        with pytest.raises(DuplicateRequestError):
            dependencies.get_idempotency_store().begin(ClientId("cli"), IdempotencyKey("k-1"))

    def test_keys_live_for_the_configured_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_settings_env(monkeypatch, IDEMPOTENCY_KEY_TTL_SECONDS="60")
        ttls: list[timedelta] = []
        monkeypatch.setattr(dependencies, "InMemoryIdempotencyStore", ttls.append)
        dependencies.get_idempotency_store()
        assert ttls == [timedelta(seconds=60)]


class TestTheRateLimiter:
    def test_generation_is_limited_per_user_of_an_exchanged_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_settings_env(monkeypatch, RATE_LIMIT_USER_GENERATE="2")
        limiter = dependencies.get_rate_limiter()
        for _ in range(2):
            limiter.check(
                client_id="cli", subject="user-1", bucket=GENERATE_BUCKET, is_service=False
            )
        with pytest.raises(RateLimitExceededError):
            limiter.check(
                client_id="cli", subject="user-1", bucket=GENERATE_BUCKET, is_service=False
            )

    def test_a_service_token_has_a_ceiling_of_its_own(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_settings_env(monkeypatch, RATE_LIMIT_USER_GENERATE="1", RATE_LIMIT_SERVICE_GENERATE="3")
        limiter = dependencies.get_rate_limiter()
        for _ in range(3):
            limiter.check(client_id="cli", subject="cli", bucket=GENERATE_BUCKET, is_service=True)
        with pytest.raises(RateLimitExceededError):
            limiter.check(client_id="cli", subject="cli", bucket=GENERATE_BUCKET, is_service=True)


class TestTheRegistry:
    def test_the_providers_repo_is_the_shipped_registry(self) -> None:
        assert dependencies.get_providers_repo().resolve("fast")

    def test_provider_keys_come_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert dependencies.get_provider_keys()["anthropic"].get_secret_value() == "sk-test"
