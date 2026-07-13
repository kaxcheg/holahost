from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork

_INSERT = text(
    "INSERT INTO guidebooks (guidebook_id, name, created_at, last_accessed_at, ip_hash) "
    "VALUES (:gid, 'n', now(), now(), 'h')"
)


@pytest.mark.integration
def test_transaction_commits(uow: PostgresUnitOfWork) -> None:
    gid = uuid.uuid4()
    with uow.transaction():
        uow.connection.execute(_INSERT, {"gid": gid})
    with uow.transaction():
        row = uow.connection.execute(
            text("SELECT name FROM guidebooks WHERE guidebook_id = :gid"), {"gid": gid}
        ).fetchone()
    assert row is not None


@pytest.mark.integration
def test_transaction_rolls_back_on_error(uow: PostgresUnitOfWork) -> None:
    gid = uuid.uuid4()
    with pytest.raises(RuntimeError, match="boom"), uow.transaction():
        uow.connection.execute(_INSERT, {"gid": gid})
        raise RuntimeError("boom")
    with uow.transaction():
        row = uow.connection.execute(
            text("SELECT 1 FROM guidebooks WHERE guidebook_id = :gid"), {"gid": gid}
        ).fetchone()
    assert row is None


@pytest.mark.integration
def test_connection_raises_without_active_transaction(uow: PostgresUnitOfWork) -> None:
    with pytest.raises(RuntimeError, match="No active transaction"):
        _ = uow.connection
