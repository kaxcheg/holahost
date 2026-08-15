"""FastAPI dependency graph — the composition root's per-request/per-process object
graph (ticket R-24). `@lru_cache` getters are true process-wide singletons (must not
be rebuilt per request: the `Engine`'s pool, the embedding model, the rate limiter's
counters, the JWKS-holding `HolahostAuth`). Plain getters are deliberately NOT
cached — FastAPI's own per-request dependency cache already guarantees a single
shared instance *within* one request's resolution graph, which is what lets a route's
`uow` field and its `documents_repo_factory`'s closed-over `uow` be the same object.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, cast

from fastapi import Depends, Header, Request
from holahost_auth import AuthConfig, HolahostAuth, TokenContext
from sqlalchemy import Engine

from application.exceptions import InvalidPayloadError
from application.ports.embedding import EmbeddingModel
from application.ports.ingestion import FileParser, TextChunker
from application.ports.rate import RateLimiter
from application.ports.repos import DocumentsRepoFactory
from application.ports.uow import UnitOfWork
from application.ports.vector import VectorSearchFactory
from config.settings import Settings
from infrastructure.db.sqlalchemy_documents_repo import SqlAlchemyDocumentsRepo
from infrastructure.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork, build_engine
from infrastructure.embedding.fastembed_embedding_model import FastembedEmbeddingModel
from infrastructure.ingestion.composite_file_parser import CompositeFileParser
from infrastructure.ingestion.recursive_text_chunker import RecursiveTextChunker
from infrastructure.rate.in_memory_rate_limiter import InMemoryRateLimiter
from infrastructure.vector.pgvector_search import PgvectorSearch

_RATE_LIMIT_WINDOW_SECONDS = 3600  # RATE_LIMIT_DEFAULT/RATE_LIMIT_INGEST are req/hour (§3.7)


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
    # extra methods, deliberately not part of the EmbeddingModel Protocol (§8.0).
    model = cast(FastembedEmbeddingModel, get_embedding_model())
    return RecursiveTextChunker(
        length_function=model.count_tokens,
        chunk_window=settings.chunk_window_tokens,
        chunk_overlap=settings.chunk_overlap_tokens,
        max_input_tokens=model.max_input_tokens(),
    )


@lru_cache
def get_rate_limiter() -> RateLimiter:
    settings = get_settings()
    return InMemoryRateLimiter(
        cap_by_bucket={"ingest": settings.rate_limit_ingest, "read": settings.rate_limit_default},
        window_seconds=_RATE_LIMIT_WINDOW_SECONDS,
    )


@lru_cache
def get_auth() -> HolahostAuth:
    settings = get_settings()
    return HolahostAuth(
        AuthConfig(
            jwks_url=settings.jwks_url,
            expected_algorithm=settings.expected_algorithm,
            expected_issuer=settings.expected_issuer,
            expected_audience=settings.expected_audience,
            clock_skew_seconds=settings.jwt_clock_skew_seconds,
        )
    )


def require_request_id(request: Request) -> None:
    """`X-Request-ID` is a contract requirement, not an optional courtesy header
    (§3.1: both real entry paths — nginx on staging/prod, the CLI orchestrator on
    dev — unconditionally attach it before a request ever reaches this service).
    Its absence means a caller is misconfigured or bypassing the intended path, and
    silently proceeding would defeat the whole point of introducing it (end-to-end
    traceability, US-R11) with no distinct signal that it happened. `request.state`
    is already populated by `RequestIdMiddleware`, which runs for every request
    (including `/health`) before any `Depends()` resolves — this dependency is what
    turns "absent" into a rejection, scoped only to the routes that need it (`/health`
    is deliberately never wired to this dependency).

    :raises InvalidPayloadError: `X-Request-ID` header is missing.
    """
    if request.state.request_id is None:
        raise InvalidPayloadError(field="X-Request-ID")


def get_current_token(
    request: Request,
    _request_id: Annotated[None, Depends(require_request_id)],
    auth: Annotated[HolahostAuth, Depends(get_auth)],
    authorization: Annotated[str | None, Header()] = None,
) -> TokenContext:
    """FastAPI dependency wrapping the singleton `HolahostAuth` instance.

    Depends on `require_request_id` first — every route needing auth also needs a
    valid `X-Request-ID`, and chaining it here (rather than listing both separately
    on each route) guarantees the request-id check runs before auth, the same way
    auth is guaranteed to run before body validation.

    Receives `auth` via `Depends(get_auth)` — not a bare `get_auth()` call — so
    `app.dependency_overrides[get_auth]` actually takes effect here too (a plain
    in-body function call bypasses FastAPI's override mechanism entirely; only
    `Depends()`-injected parameters are interceptable). Tests overriding this whole
    function directly (the common case — a fixed `TokenContext`) still never resolve
    `get_auth()`'s settings/JWKS chain either way. Stashes the token on `request.state`
    so `errors.py`'s failure logging can report `client_id`/`sub` for failures that
    occur *after* auth succeeds (e.g. rate limiting).
    """
    token = auth(authorization)
    request.state.token = token
    return token


def _rate_limit_dependency(bucket: str) -> Callable[[TokenContext, RateLimiter], None]:
    def check(
        token: Annotated[TokenContext, Depends(get_current_token)],
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        limiter.check(client_id=token.client_id, subject=token.subject, bucket=bucket)

    return check


check_ingest = _rate_limit_dependency("ingest")  # create, replace
check_read = _rate_limit_dependency("read")  # search, get, delete
