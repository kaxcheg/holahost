"""The composition root's getters for this service's own configuration."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from holahost_http import RateLimitExceededError
from tests._support.builders import make_usage
from tests._support.registry import registry_data
from tests._support.settings import set_settings_env

from application.exceptions import DuplicateRequestError
from application.use_cases.generate import GenerateUseCase
from config.registry import RegistryFile
from domain.value_objects.budget_policy import BudgetPolicy
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.client_id import ClientId
from domain.value_objects.idempotency_key import IdempotencyKey
from infrastructure.db.sqlalchemy_budget_repo import SqlAlchemyBudgetRepo
from infrastructure.db.sqlalchemy_usage_repo import SqlAlchemyUsageRepo
from infrastructure.registry.config_providers_repo import InvalidRegistryError
from interface.http import dependencies
from interface.http.edge import GENERATE_BUCKET

_GETTERS = (
    dependencies.get_settings,
    dependencies.get_engine,
    dependencies.get_registry,
    dependencies.get_providers_repo,
    dependencies.get_provider_keys,
    dependencies.get_budget_caps,
    dependencies.get_rate_limiter,
    dependencies.get_idempotency_store,
    dependencies.get_generation_provider,
    dependencies.get_budget_policies,
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


class TestTheUseCaseOfARequest:
    def test_its_repositories_read_through_the_request_s_one_unit_of_work(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # One connection slot per request: two units of work would have the budget read and the
        # usage write on different transactions of different requests' connections.
        set_settings_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        seen: list[GenerateUseCase] = []
        app = FastAPI()

        @app.get("/probe")
        def probe(
            use_case: Annotated[GenerateUseCase, Depends(dependencies.get_generate_use_case)],
        ) -> None:
            seen.append(use_case)

        TestClient(app).get("/probe")

        [use_case] = seen
        assert isinstance(use_case.budget_repo, SqlAlchemyBudgetRepo)
        assert isinstance(use_case.usage_repo, SqlAlchemyUsageRepo)
        assert use_case.budget_repo._uow is use_case.uow
        assert use_case.usage_repo._uow is use_case.uow

    def test_a_new_request_gets_a_new_unit_of_work(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_settings_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        seen: list[GenerateUseCase] = []
        app = FastAPI()

        @app.get("/probe")
        def probe(
            use_case: Annotated[GenerateUseCase, Depends(dependencies.get_generate_use_case)],
        ) -> None:
            seen.append(use_case)

        client = TestClient(app)
        client.get("/probe")
        client.get("/probe")

        first, second = seen
        assert first.uow is not second.uow
        assert first.idempotency_store is second.idempotency_store


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

    def test_the_generation_provider_is_built_for_the_shipped_registry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        assert dependencies.get_generation_provider() is dependencies.get_generation_provider()

    def test_the_budget_policy_is_the_registry_s_default_and_overrides(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data = registry_data()
        data["on_budget_exhausted"] = {"default": "reject", "overrides": {"batch": "downgrade"}}
        monkeypatch.setattr(
            dependencies, "read_registry", lambda: RegistryFile.model_validate(data)
        )

        default, overrides = dependencies.get_budget_policies()

        assert default is BudgetPolicy.REJECT
        assert overrides == {ClientId("batch"): BudgetPolicy.DOWNGRADE}

    def test_a_provider_without_an_adapter_stops_the_build_with_its_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            dependencies, "read_registry", lambda: RegistryFile.model_validate(registry_data())
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
        monkeypatch.setenv("OTHER_VENDOR_API_KEY", "sk-o")
        with pytest.raises(InvalidRegistryError, match="no adapter"):
            dependencies.get_generation_provider()
