from __future__ import annotations

from holahost_db import SqlAlchemyUnitOfWork, bind_rls_owner, translate_db_errors
from sqlalchemy import Connection, select

from application.ports.vector import SearchHit, SimilarityScore, VectorSearch
from domain.value_objects.chunk_id import ChunkId
from domain.value_objects.document_id import DocumentId
from domain.value_objects.embedding import Embedding
from domain.value_objects.page_number import PageNumber
from infrastructure.db import schema


class PgvectorSearch(VectorSearch):
    """Adapter for the `VectorSearch` port — one SQL query per call, no lock (§8.0):
    a single `SELECT ... ORDER BY ... LIMIT` is atomic under Postgres's own snapshot
    semantics, so a concurrent replace is seen entirely-before or entirely-after,
    never mixed (A-6). Runs on `uow.active_connection`, same as `SqlAlchemyDocumentsRepo`.

    Owner isolation is enforced by Postgres RLS (§8.0), bound per call via
    `_bind_owner()` — the query below does not filter by owner itself.
    """

    _uow: SqlAlchemyUnitOfWork  # narrows the inherited attribute for this adapter

    def _connection(self) -> Connection:
        return self._uow.connection()

    def _bind_owner(self) -> None:
        bind_rls_owner(self._connection(), self._owner.value)

    def _top_k_impl(
        self, document_id: DocumentId, query: Embedding, k: int, threshold: float
    ) -> list[SearchHit]:
        conn = self._connection()
        vector = list(query.value)
        distance = schema.chunks.c.embedding.cosine_distance(vector)
        max_distance = 1.0 - threshold
        stmt = (
            select(
                schema.chunks.c.id,
                schema.chunks.c.text,
                schema.chunks.c.page,
                distance.label("distance"),
            )
            .where(schema.chunks.c.document_id == document_id, distance <= max_distance)
            .order_by(distance.asc())
            .limit(k)
        )
        with translate_db_errors():
            rows = conn.execute(stmt).mappings().all()
        return [
            SearchHit(
                chunk_id=ChunkId(bytes=row["id"].bytes),
                text=row["text"],
                page=PageNumber(row["page"]),
                score=SimilarityScore(1.0 - row["distance"]),
            )
            for row in rows
        ]
