"""The composition root's object graph.

`@lru_cache` getters are true process-wide singletons and must not be rebuilt per request:
the `Engine`'s pool, the rate limiter's counters, anything expensive loaded at startup.
Plain getters are deliberately NOT cached — FastAPI's own per-request dependency cache
already guarantees a single shared instance *within* one request's resolution graph, which
is what lets a route's `uow` and an adapter factory's closed-over `uow` be the same object.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from holahost_auth import AuthConfig
from holahost_db import SqlAlchemyUnitOfWork, UnitOfWork, build_engine
from holahost_http import InMemoryRateLimiter, RateLimiter
from sqlalchemy import Engine

from config.settings import Settings
from interface.http.edge import RATE_LIMIT_WINDOW_SECONDS


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
def get_rate_limiter() -> RateLimiter:
    """Process-wide counters, consulted by `RateLimitMiddleware`.

    Keyed by `(bucket, is_service)` — the ceiling depends both on what the operation costs
    and on what the counter counts. `True` is a service token, whose `sub` is its own
    `client_id`, so one counter covers that whole integration; `False` is an exchanged
    token carrying a real user's `sub`, so the counter is per user.

    Every `(bucket, is_service)` pair `bucket_for` can return must have an entry: a missing
    one is a `KeyError` on the request that first hits it.
    """
    return InMemoryRateLimiter(cap_by_bucket={}, window_seconds=RATE_LIMIT_WINDOW_SECONDS)


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
