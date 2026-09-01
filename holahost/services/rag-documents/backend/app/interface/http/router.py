"""Document routes — UC-R1..UC-R5 (spec §7.1-§7.4, §8.2-§8.5)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Security, UploadFile
from holahost_auth import TokenContext, current_token
from holahost_http import bearer_scheme

from application.dto.documents import (
    CreateDocumentCmd,
    DeleteDocumentCmd,
    GetDocumentCmd,
    ReplaceDocumentCmd,
)
from application.dto.search import SearchCmd
from application.ports.embedding import EmbeddingModel
from application.ports.ingestion import FileParser, TextChunker, TextFragment
from application.ports.repos import DocumentsRepoFactory
from application.ports.uow import UnitOfWork
from application.ports.vector import VectorSearchFactory
from application.use_cases.create_document import CreateDocumentUseCase
from application.use_cases.delete_document import DeleteDocumentUseCase
from application.use_cases.get_document import GetDocumentUseCase
from application.use_cases.replace_document import ReplaceDocumentUseCase
from application.use_cases.search_document import SearchDocumentUseCase
from config.logging import log_event
from config.settings import Settings
from domain.value_objects.embedding import Embedding
from domain.value_objects.mime_type import MimeType
from interface.http.dependencies import (
    get_chunker,
    get_documents_repo_factory,
    get_embedding_model,
    get_parser,
    get_settings,
    get_uow,
    get_vector_search_factory,
)
from interface.http.error_schemas import (
    INGEST_RESPONSES,
    READ_RESPONSES,
    REPLACE_RESPONSES,
    SEARCH_RESPONSES,
)
from interface.http.mime_sniffer import sniff_mime_type
from interface.http.schemas import DocumentResponse, SearchRequest, SearchResponse

_bearer = bearer_scheme(
    "Platform-issued JWT, validated against the configured JWKS. Its `sub` is the "
    "owner every document is scoped to — another subject's document is answered "
    "404, never 403."
)


# Prefix is relative to the service's base path, applied once for every router by
# `interface/http/app.py`. The bearer dependency is a declaration, not behaviour: the
# schema generator reads only the route signature, so a middleware-enforced requirement
# has to be stated here or it is absent from `docs/openapi.json`.
#
# `X-Request-ID` is required just as strictly and deliberately *not* declared: it is not
# the caller's to send (both entry paths attach it), and publishing it would undo
# `MalformedRequestError`'s muteness by naming the header a caller on the wrong path needs.
router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[Security(_bearer)])


class _StageTimer:
    """Per-stage wall clock for one ingest, for `op_completed.stage_ms` (§8.7).

    Both ingest use cases run the same four stages, each with its own failure mode — a
    slow parse (a big scanned PDF), a slow embed (model contention), a slow persist (lock
    wait) — which one `duration_ms` for the whole request cannot tell apart.

    Measured in the interface layer rather than inside the use cases: the stages are ports
    the use case calls, so timing them observes the composition rather than the business
    logic.
    """

    def __init__(self) -> None:
        self._stages: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.monotonic()
        try:
            yield
        finally:
            self._stages[name] = round((time.monotonic() - start) * 1000, 3)

    def as_dict(self) -> dict[str, float] | None:
        return dict(self._stages) if self._stages else None

    def record_remainder(self, total_seconds: float) -> None:
        """Book whatever the timed stages did not account for as `persist`.

        The database work happens inside the use case's transactions, which the
        composition root has no port to wrap, so it is measured by subtraction. It also
        carries the ownership pre-check and the use case's arithmetic, both negligible
        beside a lock wait or a bulk insert. Recorded last, so the four numbers sum to
        `duration_ms`.
        """
        accounted = sum(self._stages.values())
        self._stages["persist"] = round(max(total_seconds * 1000 - accounted, 0.0), 3)


class _TimedParser:
    """Times `FileParser.parse` without the use case knowing it is being watched."""

    def __init__(self, inner: FileParser, timer: _StageTimer) -> None:
        self._inner = inner
        self._timer = timer

    def parse(self, content: bytes, mime_type: MimeType) -> list[TextFragment]:
        with self._timer.stage("parse"):
            return self._inner.parse(content, mime_type)


class _TimedChunker:
    """Times `TextChunker.split`."""

    def __init__(self, inner: TextChunker, timer: _StageTimer) -> None:
        self._inner = inner
        self._timer = timer

    def split(self, fragments: list[TextFragment]) -> list[TextFragment]:
        with self._timer.stage("chunk"):
            return self._inner.split(fragments)


class _TimedEmbedder:
    """Times `EmbeddingModel.embed_texts`; `embed_query` is not an ingest stage."""

    def __init__(self, inner: EmbeddingModel, timer: _StageTimer) -> None:
        self._inner = inner
        self._timer = timer

    def embed_texts(self, texts: list[str]) -> list[Embedding]:
        with self._timer.stage("embed"):
            return self._inner.embed_texts(texts)

    def embed_query(self, text: str) -> Embedding:
        return self._inner.embed_query(text)


def _read_upload(file: UploadFile) -> bytes:
    """Read the whole upload, then release the parser's own copy of it.

    Sync read — endpoints stay sync `def` per ADR A-9, so `file.file` is the way in.

    The release is about *when*: `FileParser` takes `bytes`, so the copy is unavoidable,
    but FastAPI's form cleanup closes the spool only after the handler returns — on the
    far side of parsing, chunking, embedding and the write. Until then a descriptor and
    its blocks are pinned per in-flight upload for nothing.

    Safe to close early: nothing downstream touches `file.file` again, and the cleanup's
    own close is a no-op on an already-closed file.
    """
    content = file.file.read()
    file.file.close()
    return content


def _log_success(
    request: Request,
    token: TokenContext,
    route: str,
    *,
    document_id: str | None = None,
    chunk_count: int | None = None,
    hits: int | None = None,
    stage_ms: dict[str, float] | None = None,
    top_score: float | None = None,
) -> None:
    # Literal keyword arguments, not a `**dict` splat: mypy rejects splatting a
    # `dict[str, object]` past `log_event`'s keyword-only `level: int`.
    start = request.state.start_time
    log_event(
        "op_completed",
        route=route,
        outcome="success",
        duration_ms=(time.monotonic() - start) * 1000,
        request_id=request.state.request_id,
        client_id=token.client_id,
        sub=token.subject,
        document_id=document_id,
        chunk_count=chunk_count,
        hits=hits,
        stage_ms=stage_ms,
        top_score=top_score,
    )


@router.post("", status_code=201, response_model=DocumentResponse, responses=INGEST_RESPONSES)
def create_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()],
    token: Annotated[TokenContext, Depends(current_token)],
    documents_repo_factory: Annotated[DocumentsRepoFactory, Depends(get_documents_repo_factory)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    parser: Annotated[FileParser, Depends(get_parser)],
    chunker: Annotated[TextChunker, Depends(get_chunker)],
    embedder: Annotated[EmbeddingModel, Depends(get_embedding_model)],
) -> DocumentResponse:
    content = _read_upload(file)
    mime_type = sniff_mime_type(content, file.filename)
    timer = _StageTimer()
    use_case = CreateDocumentUseCase(
        _TimedParser(parser, timer),
        _TimedChunker(chunker, timer),
        _TimedEmbedder(embedder, timer),
        documents_repo_factory,
        uow,
    )
    started = time.monotonic()
    view = use_case.execute(
        CreateDocumentCmd(owner=token.subject, name=name, content=content, mime_type=mime_type)
    )
    timer.record_remainder(time.monotonic() - started)
    _log_success(
        request,
        token,
        "POST /documents",
        document_id=view.document_id,
        chunk_count=view.chunk_count,
        stage_ms=timer.as_dict(),
    )
    return DocumentResponse.from_view(view)


@router.put("/{document_id}", response_model=DocumentResponse, responses=REPLACE_RESPONSES)
def replace_document(
    request: Request,
    document_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
    token: Annotated[TokenContext, Depends(current_token)],
    documents_repo_factory: Annotated[DocumentsRepoFactory, Depends(get_documents_repo_factory)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    parser: Annotated[FileParser, Depends(get_parser)],
    chunker: Annotated[TextChunker, Depends(get_chunker)],
    embedder: Annotated[EmbeddingModel, Depends(get_embedding_model)],
    name: Annotated[str | None, Form()] = None,
) -> DocumentResponse:
    content = _read_upload(file)
    mime_type = sniff_mime_type(content, file.filename)
    timer = _StageTimer()
    use_case = ReplaceDocumentUseCase(
        _TimedParser(parser, timer),
        _TimedChunker(chunker, timer),
        _TimedEmbedder(embedder, timer),
        documents_repo_factory,
        uow,
    )
    started = time.monotonic()
    view = use_case.execute(
        ReplaceDocumentCmd(
            document_id=str(document_id),
            owner=token.subject,
            content=content,
            mime_type=mime_type,
            name=name,
        )
    )
    timer.record_remainder(time.monotonic() - started)
    _log_success(
        request,
        token,
        "PUT /documents/{id}",
        document_id=view.document_id,
        chunk_count=view.chunk_count,
        stage_ms=timer.as_dict(),
    )
    return DocumentResponse.from_view(view)


@router.post("/{document_id}/search", response_model=SearchResponse, responses=SEARCH_RESPONSES)
def search_document(
    request: Request,
    document_id: uuid.UUID,
    body: SearchRequest,
    token: Annotated[TokenContext, Depends(current_token)],
    documents_repo_factory: Annotated[DocumentsRepoFactory, Depends(get_documents_repo_factory)],
    vector_search_factory: Annotated[VectorSearchFactory, Depends(get_vector_search_factory)],
    embedder: Annotated[EmbeddingModel, Depends(get_embedding_model)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchResponse:
    # §3.7's three search knobs reach the use case from here and nowhere else: the
    # application layer must not import `Settings`.
    use_case = SearchDocumentUseCase(
        documents_repo_factory,
        embedder,
        vector_search_factory,
        uow,
        top_k=settings.search_top_k,
        similarity_threshold=settings.similarity_threshold,
        max_query_length=settings.max_query_length,
    )
    result = use_case.execute(
        SearchCmd(document_id=str(document_id), owner=token.subject, query=body.query)
    )
    _log_success(
        request,
        token,
        "POST /documents/{id}/search",
        document_id=str(document_id),
        hits=len(result.hits),
        # The best match, not an average: what a search log has to answer is whether the
        # top hit cleared the bar, which is what `SIMILARITY_THRESHOLD` is calibrated
        # against. `None` on an empty result — itself the signal that nothing cleared it.
        top_score=result.hits[0].score if result.hits else None,
    )
    return SearchResponse.from_result(result)


@router.get("/{document_id}", response_model=DocumentResponse, responses=READ_RESPONSES)
def get_document(
    request: Request,
    document_id: uuid.UUID,
    token: Annotated[TokenContext, Depends(current_token)],
    documents_repo_factory: Annotated[DocumentsRepoFactory, Depends(get_documents_repo_factory)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> DocumentResponse:
    use_case = GetDocumentUseCase(documents_repo_factory, uow)
    view = use_case.execute(GetDocumentCmd(document_id=str(document_id), owner=token.subject))
    _log_success(request, token, "GET /documents/{id}", document_id=view.document_id)
    return DocumentResponse.from_view(view)


@router.delete("/{document_id}", status_code=204, response_model=None, responses=READ_RESPONSES)
def delete_document(
    request: Request,
    document_id: uuid.UUID,
    token: Annotated[TokenContext, Depends(current_token)],
    documents_repo_factory: Annotated[DocumentsRepoFactory, Depends(get_documents_repo_factory)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> None:
    use_case = DeleteDocumentUseCase(documents_repo_factory, uow)
    use_case.execute(DeleteDocumentCmd(document_id=str(document_id), owner=token.subject))
    _log_success(request, token, "DELETE /documents/{id}", document_id=str(document_id))
