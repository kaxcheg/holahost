"""UC-R3: find relevant chunks for a query (spec §8.4)."""

from __future__ import annotations

from dataclasses import dataclass

from application.dto.search import SearchCmd, SearchHitView, SearchResult
from application.exceptions import InvalidPayloadError, NotFoundError
from application.ports.embedding import EmbeddingModel
from application.ports.repos import DocumentsRepoFactory
from application.ports.uow import UnitOfWork
from application.ports.vector import VectorSearchFactory
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

    def execute(self, cmd: SearchCmd) -> SearchResult:
        """Search `cmd.document_id` for chunks relevant to `cmd.query`.

        An empty result is a valid outcome (no chunk cleared `similarity_threshold`),
        not an error.

        :raises DomainValidationError: with `field` unset — a VO invariant no caller
            input could have violated (e.g. a malformed ``document_id`` that
            interface-layer shape validation should already have rejected). Passed
            through deliberately: nothing here can turn an internal defect into a
            client-fixable answer, and the interface layer answers `500` with the
            reason in the log alone (`interface/http/errors.py`).
        :raises NotFoundError: the document does not exist, or belongs to another owner.
            Checked in the same transaction — and so the same snapshot — as the search
            itself: run as two transactions, a document deleted between them answered
            `200 {"chunks": []}`, which is the documented "nothing cleared the threshold"
            signal, leaving the caller unable to tell that apart from the `404` §7.1
            promises for that id.
        :raises InvalidPayloadError: `cmd.query` is empty or exceeds `max_query_length`.
            Checked before any database work: the query is the caller's own input and
            needs nothing from storage to judge, so failing it early also spares the
            round trip.
        :raises EmbeddingFailedError: conscious pass-through.
        :raises StorageUnavailableError: conscious pass-through.
        :raises ConcurrentUpdateError: conscious pass-through — a plain read, not
            retried (§8.6 scopes retry to replace/delete only).
        :raises IntegrityError: conscious pass-through.
        """
        owner = OwnerSubject(cmd.owner)
        document_id = DocumentId.from_str(cmd.document_id)

        # Ahead of everything else: this needs no model and no connection to decide.
        if not cmd.query.strip() or len(cmd.query) > self.max_query_length:
            raise InvalidPayloadError(field="query", limit=self.max_query_length)

        # Embedding runs outside any transaction, same reasoning as the ingest
        # pipeline (§8.2/§8.3): CPU-bound work must not hold a pooled connection. It
        # runs *before* the ownership check, which costs an embedding for a document
        # that turns out not to exist — bounded by the read rate limit, and the price
        # of the ownership check and the search sharing one transaction below.
        query_embedding = self.embedder.embed_query(cmd.query)

        documents_repo = self.documents_repo_factory(owner)
        vector_search = self.vector_search_factory(owner)

        # One transaction for both reads, not two. Two cost two pool checkouts and two
        # `_bind_owner()` round trips each search, against §3.7's 500 ms p95 budget on a
        # pool of 5 — and, worse, put the ownership check and the search in different
        # snapshots, so a document deleted between them came back as an empty result
        # instead of a 404 (see `:raises NotFoundError:`).
        #
        # No lock: search accepts a possibly stale-but-consistent result during a
        # concurrent replace, trading it for not blocking the hot search path. The
        # ownership pre-check exists only to tell 404 apart from "nothing matched" —
        # `top_k` is owner-scoped by RLS either way (§8.0), so it can never serve
        # another subject's chunks whatever this check answers.
        with self.uow:
            if documents_repo.get(document_id) is None:
                raise NotFoundError
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
