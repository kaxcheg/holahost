"""Document routes — UC-R1..UC-R5 (spec §7.1-§7.4, §8.2-§8.5)."""

from __future__ import annotations

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from holahost_auth import TokenContext

from application.dto.documents import (
    CreateDocumentCmd,
    DeleteDocumentCmd,
    GetDocumentCmd,
    ReplaceDocumentCmd,
)
from application.dto.search import SearchCmd
from application.ports.embedding import EmbeddingModel
from application.ports.ingestion import FileParser, TextChunker
from application.ports.repos import DocumentsRepoFactory
from application.ports.uow import UnitOfWork
from application.ports.vector import VectorSearchFactory
from application.use_cases.create_document import CreateDocumentUseCase
from application.use_cases.delete_document import DeleteDocumentUseCase
from application.use_cases.get_document import GetDocumentUseCase
from application.use_cases.replace_document import ReplaceDocumentUseCase
from application.use_cases.search_document import SearchDocumentUseCase
from config.logging import log_event
from interface.http.dependencies import (
    check_ingest,
    check_read,
    get_chunker,
    get_current_token,
    get_documents_repo_factory,
    get_embedding_model,
    get_parser,
    get_uow,
    get_vector_search_factory,
)
from interface.http.mime_sniffer import sniff_mime_type
from interface.http.schemas import DocumentResponse, SearchRequest, SearchResponse

# Relative to the service's own base path, which `interface/http/app.py` applies once for
# every router (see `api_base.py`) — a router does not get to choose the segment it is
# published under.
router = APIRouter(prefix="/documents", tags=["documents"])


def _log_success(
    request: Request,
    token: TokenContext,
    route: str,
    *,
    document_id: str | None = None,
    chunk_count: int | None = None,
    hits: int | None = None,
) -> None:
    # Literal keyword arguments throughout — not a `**dict` splat: log_event's
    # `level: int = ...` keyword-only param ahead of `**fields: object` makes mypy
    # conservatively reject any splatted `dict[str, object]` (it can't prove the dict
    # excludes a "level" key), even though no caller here ever means to set it.
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
    )


@router.post("", status_code=201, response_model=DocumentResponse)
def create_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()],
    token: Annotated[TokenContext, Depends(get_current_token)],
    _rate: Annotated[None, Depends(check_ingest)],
    documents_repo_factory: Annotated[DocumentsRepoFactory, Depends(get_documents_repo_factory)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    parser: Annotated[FileParser, Depends(get_parser)],
    chunker: Annotated[TextChunker, Depends(get_chunker)],
    embedder: Annotated[EmbeddingModel, Depends(get_embedding_model)],
) -> DocumentResponse:
    content = file.file.read()  # sync read — endpoints stay sync `def` per ADR A-9
    mime_type = sniff_mime_type(content, file.filename)
    use_case = CreateDocumentUseCase(parser, chunker, embedder, documents_repo_factory, uow)
    view = use_case.execute(
        CreateDocumentCmd(owner=token.subject, name=name, content=content, mime_type=mime_type)
    )
    _log_success(
        request,
        token,
        "POST /documents",
        document_id=view.document_id,
        chunk_count=view.chunk_count,
    )
    return DocumentResponse.from_view(view)


@router.put("/{document_id}", response_model=DocumentResponse)
def replace_document(
    request: Request,
    document_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
    token: Annotated[TokenContext, Depends(get_current_token)],
    _rate: Annotated[None, Depends(check_ingest)],
    documents_repo_factory: Annotated[DocumentsRepoFactory, Depends(get_documents_repo_factory)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    parser: Annotated[FileParser, Depends(get_parser)],
    chunker: Annotated[TextChunker, Depends(get_chunker)],
    embedder: Annotated[EmbeddingModel, Depends(get_embedding_model)],
    name: Annotated[str | None, Form()] = None,
) -> DocumentResponse:
    content = file.file.read()
    mime_type = sniff_mime_type(content, file.filename)
    use_case = ReplaceDocumentUseCase(parser, chunker, embedder, documents_repo_factory, uow)
    view = use_case.execute(
        ReplaceDocumentCmd(
            document_id=str(document_id),
            owner=token.subject,
            content=content,
            mime_type=mime_type,
            name=name,
        )
    )
    _log_success(
        request,
        token,
        "PUT /documents/{id}",
        document_id=view.document_id,
        chunk_count=view.chunk_count,
    )
    return DocumentResponse.from_view(view)


@router.post("/{document_id}/search", response_model=SearchResponse)
def search_document(
    request: Request,
    document_id: uuid.UUID,
    body: SearchRequest,
    token: Annotated[TokenContext, Depends(get_current_token)],
    _rate: Annotated[None, Depends(check_read)],
    documents_repo_factory: Annotated[DocumentsRepoFactory, Depends(get_documents_repo_factory)],
    vector_search_factory: Annotated[VectorSearchFactory, Depends(get_vector_search_factory)],
    embedder: Annotated[EmbeddingModel, Depends(get_embedding_model)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> SearchResponse:
    use_case = SearchDocumentUseCase(documents_repo_factory, embedder, vector_search_factory, uow)
    result = use_case.execute(
        SearchCmd(document_id=str(document_id), owner=token.subject, query=body.query)
    )
    _log_success(
        request,
        token,
        "POST /documents/{id}/search",
        document_id=str(document_id),
        hits=len(result.hits),
    )
    return SearchResponse.from_result(result)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    request: Request,
    document_id: uuid.UUID,
    token: Annotated[TokenContext, Depends(get_current_token)],
    _rate: Annotated[None, Depends(check_read)],
    documents_repo_factory: Annotated[DocumentsRepoFactory, Depends(get_documents_repo_factory)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> DocumentResponse:
    use_case = GetDocumentUseCase(documents_repo_factory, uow)
    view = use_case.execute(GetDocumentCmd(document_id=str(document_id), owner=token.subject))
    _log_success(request, token, "GET /documents/{id}", document_id=view.document_id)
    return DocumentResponse.from_view(view)


@router.delete("/{document_id}", status_code=204, response_model=None)
def delete_document(
    request: Request,
    document_id: uuid.UUID,
    token: Annotated[TokenContext, Depends(get_current_token)],
    _rate: Annotated[None, Depends(check_read)],
    documents_repo_factory: Annotated[DocumentsRepoFactory, Depends(get_documents_repo_factory)],
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> None:
    use_case = DeleteDocumentUseCase(documents_repo_factory, uow)
    use_case.execute(DeleteDocumentCmd(document_id=str(document_id), owner=token.subject))
    _log_success(request, token, "DELETE /documents/{id}", document_id=str(document_id))
