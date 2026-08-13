from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, RowMapping, delete, insert, select, text, update

from application.exceptions import NotFoundError
from application.ports.repos import DocumentsRepo
from domain.entities.chunk import Chunk
from domain.entities.document import Document
from domain.value_objects.document_id import DocumentId
from domain.value_objects.document_name import DocumentName
from domain.value_objects.mime_type import MimeType
from domain.value_objects.owner_subject import OwnerSubject
from infrastructure.db import schema
from infrastructure.db.errors import translate_db_errors
from infrastructure.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork


def _document_values(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "owner_subject": document.owner.value,
        "name": document.name.value,
        "mime_type": document.mime_type.value,
        "chunk_count": document.chunk_count,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


def _document_from_row(row: RowMapping) -> Document:
    return Document.from_repo(
        id=DocumentId(bytes=row["id"].bytes),
        owner=OwnerSubject(row["owner_subject"]),
        name=DocumentName(row["name"]),
        mime_type=MimeType(row["mime_type"]),
        chunk_count=row["chunk_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _chunk_values(chunk: Chunk) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "idx": chunk.index.value,
        "text": chunk.text,
        "page": chunk.page.value,
        "embedding": list(chunk.embedding.value),
    }


class SqlAlchemyDocumentsRepo(DocumentsRepo):
    """Adapter for the `DocumentsRepo` port (application/ports/repos.py) — persists
    `Document` rows together with the `Chunk` rows they own (§4.3: one repo for the
    aggregate, chunks are never written independently). Runs on `uow.active_connection`
    — every call happens inside an active transaction (§8.0, clarifications.md item 1),
    so there is no standalone-connection branch here.

    Owner isolation is enforced by Postgres RLS (§8.0), bound per call via
    `_bind_owner()` — no method here filters by owner in its own SQL.
    """

    _uow: SqlAlchemyUnitOfWork  # narrows the inherited attribute for this adapter

    def _connection(self) -> Connection:
        if self._uow.active_connection is None:
            raise RuntimeError("no active transaction")
        return self._uow.active_connection

    def _bind_owner(self) -> None:
        # `SET LOCAL` does not accept a bind parameter (Postgres only takes a literal
        # there) — `set_config(..., is_local=true)` is the parameterized equivalent,
        # same transaction-scoped reset-on-commit/rollback behavior (verified against
        # a real syntax error from the naive `SET LOCAL ... = :owner` form).
        with translate_db_errors():
            self._connection().execute(
                text("SELECT set_config('app.current_owner', :owner, true)"),
                {"owner": self._owner.value},
            )

    def _add_impl(self, document: Document) -> None:
        if document.owner != self._owner:
            raise RuntimeError("add() called with mismatched owner")
        if document.chunks is None:
            raise RuntimeError("add() called with unset chunks")
        with translate_db_errors():
            conn = self._connection()
            conn.execute(insert(schema.documents).values(_document_values(document)))
            conn.execute(insert(schema.chunks), [_chunk_values(c) for c in document.chunks])

    def _get_impl(self, document_id: DocumentId, *, lock: bool) -> Document | None:
        stmt = select(schema.documents).where(schema.documents.c.id == document_id)
        if lock:
            stmt = stmt.with_for_update()
        with translate_db_errors():
            row = self._connection().execute(stmt).mappings().one_or_none()
        return _document_from_row(row) if row is not None else None

    def _update_impl(self, document: Document) -> None:
        if document.owner != self._owner:
            raise RuntimeError("update() called with mismatched owner")
        values = _document_values(document)
        del values["id"]
        with translate_db_errors():
            conn = self._connection()
            result = conn.execute(
                update(schema.documents).where(schema.documents.c.id == document.id).values(values)
            )
            if result.rowcount == 0:
                raise NotFoundError
            if document.chunks is not None:
                conn.execute(
                    delete(schema.chunks).where(schema.chunks.c.document_id == document.id)
                )
                conn.execute(insert(schema.chunks), [_chunk_values(c) for c in document.chunks])

    def _delete_impl(self, document_id: DocumentId) -> None:
        with translate_db_errors():
            result = self._connection().execute(
                delete(schema.documents).where(schema.documents.c.id == document_id)
            )
            if result.rowcount == 0:
                raise NotFoundError
