from __future__ import annotations

from datetime import UTC, datetime

import pytest

from domain.entities.guidebook import Guidebook
from domain.value_objects.guidebook_name import GuidebookName
from domain.value_objects.ip_hash import IpHash
from infrastructure.db.sqlalchemy.postgres_guidebooks_repo import PostgresGuidebooksRepo
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork

_IP = "0" * 64


def _make() -> Guidebook:
    return Guidebook.create(name=GuidebookName("My Book"), ip_hash=IpHash(_IP))


@pytest.mark.integration
def test_add_then_get_round_trips(uow: PostgresUnitOfWork) -> None:
    gb = _make()
    with uow.transaction():
        PostgresGuidebooksRepo(uow).add(gb)
    with uow.transaction():
        loaded = PostgresGuidebooksRepo(uow).get(gb.id)
    assert loaded is not None
    assert loaded.id == gb.id
    assert loaded.name.value == "My Book"
    assert loaded.created_at == gb.created_at  # explicit-timestamp persistence (UTC round-trip)
    assert loaded.ip_hash.value == _IP


@pytest.mark.integration
def test_get_missing_returns_none(uow: PostgresUnitOfWork) -> None:
    with uow.transaction():
        assert PostgresGuidebooksRepo(uow).get(_make().id) is None


@pytest.mark.integration
def test_delete_removes_row(uow: PostgresUnitOfWork) -> None:
    gb = _make()
    repo = PostgresGuidebooksRepo(uow)
    with uow.transaction():
        repo.add(gb)
        repo.delete(gb.id)
        assert repo.get(gb.id) is None


@pytest.mark.integration
def test_update_persists_full_row(uow: PostgresUnitOfWork) -> None:
    gb = _make()
    repo = PostgresGuidebooksRepo(uow)
    with uow.transaction():
        repo.add(gb)
    gb.last_accessed_at = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)  # deterministic mutation
    with uow.transaction():
        repo.update(gb)
    with uow.transaction():
        loaded = repo.get(gb.id)
    assert loaded is not None
    assert loaded.last_accessed_at == gb.last_accessed_at  # mutated value persisted
    assert loaded.created_at == gb.created_at  # immutable column untouched by the full-row write
    assert loaded.name.value == "My Book"
