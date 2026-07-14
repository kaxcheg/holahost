from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import RowMapping, delete, insert, select, update

from domain.entities.guidebook import Guidebook
from domain.value_objects.guidebook_id import GuidebookId
from domain.value_objects.guidebook_name import GuidebookName
from domain.value_objects.ip_hash import IpHash
from infrastructure.db.sqlalchemy import schema
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork


def _to_values(guidebook: Guidebook) -> dict[str, Any]:
    """Map a ``Guidebook`` to its column→value dict (entity attributes never appear in SQL)."""
    return {
        "guidebook_id": guidebook.id,
        "name": guidebook.name.value,
        "created_at": guidebook.created_at,
        "last_accessed_at": guidebook.last_accessed_at,
        "ip_hash": guidebook.ip_hash.value,
    }


def _from_row(row: RowMapping) -> Guidebook:
    """Reconstruct a ``Guidebook`` from a result row (schema-facing half; delegates to from_repo)."""
    return Guidebook.from_repo(
        id=GuidebookId(bytes=row["guidebook_id"].bytes),
        name=GuidebookName(row["name"]),
        created_at=row["created_at"],
        last_accessed_at=row["last_accessed_at"],
        ip_hash=IpHash(row["ip_hash"]),
    )


class PostgresGuidebooksRepo:
    """Postgres adapter for the ``GuidebooksRepo`` port (spec §4.2); runs on ``uow.connection``.

    SQLAlchemy Core: statements never enumerate columns — the column↔attribute bridge and the
    value-object conversion live solely in the in-module Data Mapper (``_to_values`` / ``_from_row``).
    """

    def __init__(self, uow: PostgresUnitOfWork) -> None:
        self._uow = uow

    def get(self, guidebook_id: GuidebookId) -> Guidebook | None:
        row = (
            self._uow.connection.execute(
                select(schema.guidebooks).where(schema.guidebooks.c.guidebook_id == guidebook_id)
            )
            .mappings()
            .one_or_none()  # lookup by PK → at most one row
        )
        return None if row is None else _from_row(row)

    def add(self, guidebook: Guidebook) -> None:
        self._uow.connection.execute(insert(schema.guidebooks).values(_to_values(guidebook)))

    def update(self, guidebook: Guidebook) -> None:
        # Full-row write of the current state (C-12 p.4); the PK is the WHERE key, not a SET target.
        values = _to_values(guidebook)
        del values["guidebook_id"]
        self._uow.connection.execute(
            update(schema.guidebooks)
            .where(schema.guidebooks.c.guidebook_id == guidebook.id)
            .values(values)
        )

    def delete(self, guidebook_id: GuidebookId) -> None:
        self._uow.connection.execute(
            delete(schema.guidebooks).where(schema.guidebooks.c.guidebook_id == guidebook_id)
        )


if TYPE_CHECKING:
    from application.ports.repos import GuidebooksRepo

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: PostgresGuidebooksRepo) -> GuidebooksRepo:
        return x
