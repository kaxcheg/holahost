"""UC-R3: find relevant chunks for a query (spec §8.4)."""

from __future__ import annotations

from dataclasses import dataclass

from application.dto.search import SearchCmd, SearchHitView, SearchResult
from application.exceptions import InvalidPayloadError, NotFoundError
from application.limits import MAX_QUERY_LENGTH, SEARCH_TOP_K, SIMILARITY_THRESHOLD
from application.ports.embedding import EmbeddingModel
from application.ports.repos import DocumentsRepoFactory
from application.ports.uow import UnitOfWork
from application.ports.vector import VectorSearchFactory
from application.use_cases._internal_errors import wrap_value_error
from domain.value_objects.document_id import DocumentId
from domain.value_objects.owner_subject import OwnerSubject


@dataclass
class SearchDocumentUseCase:
    """UC-R3: embed the query and return its top-K most similar chunks."""

    documents_repo_factory: DocumentsRepoFactory
    embedder: EmbeddingModel
    vector_search_factory: VectorSearchFactory
    uow: UnitOfWork

    @wrap_value_error
    def execute(self, cmd: SearchCmd) -> SearchResult:
        """Search `cmd.document_id` for chunks relevant to `cmd.query`.

        An empty result is a valid outcome (no chunk cleared `SIMILARITY_THRESHOLD`),
        not an error.

        :raises ApplicationError: wraps a bare ``ValueError`` (e.g. a malformed
            ``document_id`` that should have already been rejected by interface-layer
            shape validation) — an internal defect, never client-fixable.
        :raises NotFoundError: the document does not exist, or belongs to another owner.
        :raises InvalidPayloadError: `cmd.query` is empty or exceeds `MAX_QUERY_LENGTH`.
        :raises EmbeddingFailedError: conscious pass-through.
        :raises StorageUnavailableError: conscious pass-through.
        :raises ConcurrentUpdateError: conscious pass-through — a plain read, not
            retried (§8.6 scopes retry to replace/delete only).
        :raises IntegrityError: conscious pass-through.
        """
        owner = OwnerSubject(cmd.owner)
        document_id = DocumentId.from_str(cmd.document_id)
        documents_repo = self.documents_repo_factory(owner)
        vector_search = self.vector_search_factory(owner)

        # No lock: search accepts a possibly stale-but-consistent result during a
        # concurrent replace/delete, trading it for not blocking the hot search path.
        # Still runs inside a transaction — every DocumentsRepo call does (§8.0).
        with self.uow:
            document = documents_repo.get(document_id)
            if document is None:
                raise NotFoundError

        if not cmd.query.strip():
            raise InvalidPayloadError(field="query")
        if len(cmd.query) > MAX_QUERY_LENGTH:
            raise InvalidPayloadError(field="query", limit=MAX_QUERY_LENGTH)

        # Embedding runs outside any transaction, same reasoning as the ingest
        # pipeline (§8.2/§8.3): CPU-bound work must not hold a pooled connection.
        query_embedding = self.embedder.embed_query(cmd.query)

        # No lock: search accepts a possibly stale-but-consistent result. A separate,
        # short transaction — reusing self.uow sequentially is safe (§8.0).
        with self.uow:
            hits = vector_search.top_k(
                document_id, query_embedding, SEARCH_TOP_K, SIMILARITY_THRESHOLD
            )

        return SearchResult(
            hits=[
                SearchHitView(
                    chunk_id=str(hit.chunk_id),
                    text=hit.text,
                    page=hit.page.value,
                    score=hit.score.value,
                )
                for hit in hits
            ]
        )
