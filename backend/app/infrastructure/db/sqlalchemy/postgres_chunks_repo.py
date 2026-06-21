from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import RowMapping, insert, select

from domain.entities.chunk import Chunk
from domain.value_objects.chunk_id import ChunkId
from domain.value_objects.embedding import Embedding
from domain.value_objects.guidebook_id import GuidebookId
from infrastructure.db.sqlalchemy import schema
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork


def _to_values(chunk: Chunk) -> dict[str, Any]:
    """Map a ``Chunk`` to its column→value dict (embedding serialised to BYTEA bytes)."""
    return {
        "id": chunk.id,
        "guidebook_id": chunk.guidebook_id,
        "ordinal": chunk.ordinal,
        "text": chunk.text,
        "embedding": chunk.embedding.to_bytes(),
    }


def _from_row(row: RowMapping) -> Chunk:
    return Chunk.from_repo(
        id=ChunkId(bytes=row["id"].bytes),
        guidebook_id=GuidebookId(bytes=row["guidebook_id"].bytes),
        ordinal=row["ordinal"],
        text=row["text"],
        embedding=Embedding.from_bytes(bytes(row["embedding"])),  # BYTEA memoryview -> bytes
    )


class PostgresChunksRepo:
    """Postgres adapter for the ``ChunksRepo`` port (spec §4.3); runs on ``uow.connection``."""

    def __init__(self, uow: PostgresUnitOfWork) -> None:
        self._uow = uow

    def list_for_guidebook(self, guidebook_id: GuidebookId) -> list[Chunk]:
        rows = (
            self._uow.connection.execute(
                select(schema.chunks)
                .where(schema.chunks.c.guidebook_id == guidebook_id)
                .order_by(schema.chunks.c.ordinal)
            )
            .mappings()
            .all()
        )
        return [_from_row(row) for row in rows]

    def bulk_add(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        # A list of param dicts drives a single executemany INSERT.
        self._uow.connection.execute(insert(schema.chunks), [_to_values(c) for c in chunks])


if TYPE_CHECKING:
    from application.ports.repos import ChunksRepo

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: PostgresChunksRepo) -> ChunksRepo:
        return x
