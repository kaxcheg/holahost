"""FastAPI dependency graph — the composition root's per-request/per-process object
graph. `@lru_cache` getters are true process-wide singletons (must not
be rebuilt per request: the `Engine`'s pool, the embedding model, the rate limiter's
counters, the JWKS-holding `HolahostAuth`). Plain getters are deliberately NOT
cached — FastAPI's own per-request dependency cache already guarantees a single
shared instance *within* one request's resolution graph, which is what lets a route's
`uow` field and its `documents_repo_factory`'s closed-over `uow` be the same object.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, cast

from fastapi import Depends
from holahost_auth import AuthConfig
from holahost_db import SqlAlchemyUnitOfWork
from holahost_http import InMemoryRateLimiter, RateLimiter
from sqlalchemy import Engine

from application.ports.embedding import EmbeddingModel
from application.ports.ingestion import FileParser, TextChunker
from application.ports.repos import DocumentsRepoFactory
from application.ports.uow import UnitOfWork
from application.ports.vector import VectorSearchFactory
from config.settings import Settings
from infrastructure.db.engine import build_engine
from infrastructure.db.sqlalchemy_documents_repo import SqlAlchemyDocumentsRepo
from infrastructure.embedding.fastembed_embedding_model import FastembedEmbeddingModel
from infrastructure.ingestion.composite_file_parser import CompositeFileParser
from infrastructure.ingestion.recursive_text_chunker import RecursiveTextChunker
from infrastructure.vector.pgvector_search import PgvectorSearch
from interface.http.edge import INGEST_BUCKET, RATE_LIMIT_WINDOW_SECONDS, READ_BUCKET


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings().database_url.get_secret_value())


def get_uow(engine: Annotated[Engine, Depends(get_engine)]) -> UnitOfWork:
    return SqlAlchemyUnitOfWork(engine)


def get_documents_repo_factory(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> DocumentsRepoFactory:
    return lambda owner: SqlAlchemyDocumentsRepo(uow, owner)


def get_vector_search_factory(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> VectorSearchFactory:
    return lambda owner: PgvectorSearch(uow, owner)


@lru_cache
def get_embedding_model() -> EmbeddingModel:
    settings = get_settings()
    return FastembedEmbeddingModel(settings.embedding_model, settings.embedding_cache_dir)


@lru_cache
def get_parser() -> FileParser:
    return CompositeFileParser()


@lru_cache
def get_chunker() -> TextChunker:
    settings = get_settings()
    # cast, not assert: get_embedding_model() only ever constructs FastembedEmbeddingModel
    # (the sole EmbeddingModel implementation); count_tokens/max_input_tokens are its own
    # extra methods, deliberately not part of the EmbeddingModel Protocol.
    model = cast(FastembedEmbeddingModel, get_embedding_model())
    return RecursiveTextChunker(
        length_function=model.count_tokens,
        chunk_window=settings.chunk_window_tokens,
        chunk_overlap=settings.chunk_overlap_tokens,
        max_input_tokens=model.max_input_tokens(),
    )


@lru_cache
def get_rate_limiter() -> RateLimiter:
    """Process-wide counters, consulted by `RateLimitMiddleware`.

    Keyed by `(bucket, is_service)` — the ceiling depends both on what the operation
    costs and on what the counter counts. `True` is a service token, whose `sub` is its
    own `client_id`, so one counter covers that whole integration; `False` is an
    exchanged token carrying a real user's `sub`, so the counter is per user.
    """
    settings = get_settings()
    return InMemoryRateLimiter(
        cap_by_bucket={
            (INGEST_BUCKET, False): settings.rate_limit_user_ingest,
            (READ_BUCKET, False): settings.rate_limit_user_read,
            (INGEST_BUCKET, True): settings.rate_limit_service_ingest,
            (READ_BUCKET, True): settings.rate_limit_service_read,
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
