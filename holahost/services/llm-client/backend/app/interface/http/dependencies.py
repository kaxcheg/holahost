"""The composition root's object graph.

`@lru_cache` getters are true process-wide singletons and must not be rebuilt per request:
the `Engine`'s pool, the rate limiter's counters, anything expensive loaded at startup.
Plain getters are deliberately NOT cached — FastAPI's own per-request dependency cache
already guarantees a single shared instance *within* one request's resolution graph, which
is what lets a route's `uow` and an adapter factory's closed-over `uow` be the same object.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import timedelta
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from holahost_auth import AuthConfig
from holahost_db import SqlAlchemyUnitOfWork, UnitOfWork, build_engine
from holahost_http import InMemoryRateLimiter, RateLimiter
from pydantic import SecretStr
from sqlalchemy import Engine

from application.ports.idempotency import IdempotencyStore
from application.ports.providers import ProvidersRepo
from config.provider_keys import read_provider_keys
from config.registry import RegistryFile, read_registry
from config.settings import Settings
from domain.value_objects.budget_scope import BudgetScope
from domain.value_objects.token_count import TokenCount
from domain.value_objects.usage import Usage
from infrastructure.idempotency.in_memory_idempotency_store import InMemoryIdempotencyStore
from infrastructure.registry.config_providers_repo import load_providers_repo
from interface.http.edge import GENERATE_BUCKET, RATE_LIMIT_WINDOW_SECONDS


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache
def get_engine() -> Engine:
    # A service whose schema needs a per-connection codec (pgvector, say) wraps this in its
    # own `infrastructure/db/engine.py` and passes `on_connect=`.
    return build_engine(get_settings().database_url.get_secret_value())


def get_uow(engine: Annotated[Engine, Depends(get_engine)]) -> UnitOfWork:
    return SqlAlchemyUnitOfWork(engine)


@lru_cache
def get_registry() -> RegistryFile:
    return read_registry()


@lru_cache
def get_providers_repo() -> ProvidersRepo:
    return load_providers_repo(get_registry())


@lru_cache
def get_provider_keys() -> Mapping[str, SecretStr]:
    return read_provider_keys(get_registry(), os.environ)


@lru_cache
def get_budget_caps() -> Mapping[BudgetScope, Usage]:
    """The budget's ceilings per scope, as the budget repository takes them."""
    settings = get_settings()
    return {
        BudgetScope.CLIENT: _usage(
            settings.budget_cap_client_input_tokens, settings.budget_cap_client_output_tokens
        ),
        BudgetScope.CLIENT_DOWNGRADE: _usage(
            settings.budget_cap_client_downgrade_input_tokens,
            settings.budget_cap_client_downgrade_output_tokens,
        ),
        BudgetScope.PROVIDER: _usage(
            settings.budget_cap_provider_input_tokens, settings.budget_cap_provider_output_tokens
        ),
    }


def _usage(input_tokens: int, output_tokens: int) -> Usage:
    return Usage(input_tokens=TokenCount(input_tokens), output_tokens=TokenCount(output_tokens))


@lru_cache
def get_idempotency_store() -> IdempotencyStore:
    return InMemoryIdempotencyStore(timedelta(seconds=get_settings().idempotency_key_ttl_seconds))


@lru_cache
def get_rate_limiter() -> RateLimiter:
    """Process-wide counters, consulted by `RateLimitMiddleware`.

    Keyed by `(bucket, is_service)` — the ceiling depends both on what the operation costs
    and on what the counter counts. `True` is a service token, whose `sub` is its own
    `client_id`, so one counter covers that whole integration; `False` is an exchanged
    token carrying a real user's `sub`, so the counter is per user.

    Every `(bucket, is_service)` pair `bucket_for` can return must have an entry: a missing
    one is a `KeyError` on the request that first hits it.
    """
    settings = get_settings()
    return InMemoryRateLimiter(
        cap_by_bucket={
            (GENERATE_BUCKET, False): settings.rate_limit_user_generate,
            (GENERATE_BUCKET, True): settings.rate_limit_service_generate,
        },
        window_seconds=RATE_LIMIT_WINDOW_SECONDS,
    )


def get_auth_config() -> AuthConfig:
    """Validation config for `HolahostAuthMiddleware`.

    Built with no arguments: `AuthConfig` reads its own five variables from the
    environment, and their names are a platform contract rather than this service's
    choice — so there is nothing here to map and nothing to keep in step.

    Read once by `create_app()` when it builds the middleware stack, not per request:
    middleware is constructed at app-build time, so there is no `Depends()` graph to
    resolve it through and nothing to cache.
    """
    return AuthConfig()
