from __future__ import annotations

import pytest
from sqlalchemy import text

from infrastructure.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration

_SET_OWNER = text("SET LOCAL app.current_owner = 'o'")
_INSERT_DOCUMENT = text(
    "INSERT INTO documents (id, owner_subject, name, mime_type, chunk_count, "
    "created_at, updated_at) VALUES (gen_random_uuid(), 'o', 'n', 'text/plain', "
    "1, now(), now())"
)
_COUNT_DOCUMENTS = text("SELECT count(*) FROM documents")


def test_commits_on_clean_exit(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        assert uow.active_connection is not None
        uow.active_connection.execute(_SET_OWNER)  # RLS WITH CHECK needs this bound (§8.0)
        uow.active_connection.execute(_INSERT_DOCUMENT)
    with uow:
        assert uow.active_connection is not None
        uow.active_connection.execute(_SET_OWNER)
        count = uow.active_connection.execute(_COUNT_DOCUMENTS).scalar_one()
    assert count == 1


def test_rolls_back_on_exception(uow: SqlAlchemyUnitOfWork) -> None:
    with pytest.raises(ValueError), uow:
        assert uow.active_connection is not None
        uow.active_connection.execute(_SET_OWNER)
        uow.active_connection.execute(_INSERT_DOCUMENT)
        raise ValueError("boom")
    with uow:
        assert uow.active_connection is not None
        uow.active_connection.execute(_SET_OWNER)
        count = uow.active_connection.execute(_COUNT_DOCUMENTS).scalar_one()
    assert count == 0


def test_reentrant_across_sequential_blocks(uow: SqlAlchemyUnitOfWork) -> None:
    with uow:
        pass
    with uow:
        pass  # second, independent transaction on the same instance — must not raise
