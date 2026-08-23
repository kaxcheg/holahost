"""UC-R3: find relevant chunks for a query (spec §8.4)."""

from __future__ import annotations

from dataclasses import dataclass

from application.dto.search import SearchCmd, SearchHitView, SearchResult
from application.exceptions import InvalidPayloadError, NotFoundError
from application.ports.embedding import EmbeddingModel
from application.ports.repos import DocumentsRepoFactory
from application.ports.uow import UnitOfWork
from application.ports.vector import VectorSearchFactory
from application.use_cases._internal_errors import wrap_value_error
from domain.value_objects.document_id import DocumentId
from domain.value_objects.owner_subject import OwnerSubject


@dataclass
class SearchDocumentUseCase:
    """UC-R3: embed the query and return its top-K most similar chunks.

    The three search parameters are injected, not read from module constants: §3.7 makes
    them environment configuration (`SEARCH_TOP_K`, `SIMILARITY_THRESHOLD`,
    `MAX_QUERY_LENGTH`), and the threshold in particular is explicitly provisional —
    "calibrated on real guidebooks later". Constants made those settings unreadable:
    every one of them had zero readers while this use case used a literal, so turning the
    knob in `.env` changed nothing at all. Wired from `Settings` in the composition root,
    which is also the only layer allowed to know `Settings` exists.
    """

    documents_repo_factory: DocumentsRepoFactory
    embedder: EmbeddingModel
    vector_search_factory: VectorSearchFactory
    uow: UnitOfWork
    top_k: int
    similarity_threshold: float
    max_query_length: int

    @wrap_value_error
    def execute(self, cmd: SearchCmd) -> SearchResult:
        """Search `cmd.document_id` for chunks relevant to `cmd.query`.

        An empty result is a valid outcome (no chunk cleared `similarity_threshold`),
        not an error.

        :raises ApplicationError: wraps a bare ``ValueError`` (e.g. a malformed
            ``document_id`` that should have already been rejected by interface-layer
            shape validation) — an internal defect, never client-fixable.
        :raises NotFoundError: the document does not exist, or belongs to another owner.
        :raises InvalidPayloadError: `cmd.query` is empty or exceeds `max_query_length`.
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
        if len(cmd.query) > self.max_query_length:
            raise InvalidPayloadError(field="query", limit=self.max_query_length)

        # Embedding runs outside any transaction, same reasoning as the ingest
        # pipeline (§8.2/§8.3): CPU-bound work must not hold a pooled connection.
        query_embedding = self.embedder.embed_query(cmd.query)

        # No lock: search accepts a possibly stale-but-consistent result. A separate,
        # short transaction — reusing self.uow sequentially is safe (§8.0).
        with self.uow:
            hits = vector_search.top_k(
                document_id, query_embedding, self.top_k, self.similarity_threshold
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
