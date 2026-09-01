from __future__ import annotations

import pytest
from holahost_db import SqlAlchemyUnitOfWork, translate_db_errors
from sqlalchemy import create_engine, insert
from tests._support.builders import make_chunk, make_document_with_chunks

from application.exceptions import NotFoundError
from application.ports.exceptions import IntegrityError
from domain.entities.document import Document
from domain.value_objects.document_id import DocumentId
from domain.value_objects.document_name import DocumentName
from domain.value_objects.mime_type import MimeType
from domain.value_objects.owner_subject import OwnerSubject
from infrastructure.db import schema
from infrastructure.db.sqlalchemy_documents_repo import SqlAlchemyDocumentsRepo

pytestmark = pytest.mark.integration


def _chunk_rows(
    repo: SqlAlchemyDocumentsRepo, uow: SqlAlchemyUnitOfWork, document_id: DocumentId
) -> list[object]:
    """Reads `chunks` rows directly, bypassing the repo's own SQL — needs the
    transaction's owner bound first (RLS applies to this raw query too, §8.0), which
    `repo._bind_owner()` does using whichever owner `repo` was constructed with."""
    repo._bind_owner()
    assert uow.active_connection is not None
    return list(
        uow.active_connection.execute(
            schema.chunks.select().where(schema.chunks.c.document_id == document_id)
        )
        .mappings()
        .all()
    )


def test_add_then_get_roundtrips(uow: SqlAlchemyUnitOfWork) -> None:
    repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("user-1"))
    document = make_document_with_chunks(owner="user-1", chunk_count=2)
    with uow:
        repo.add(document)
    with uow:
        fetched = repo.get(document.id)
    assert fetched is not None
    assert fetched.id == document.id
    assert fetched.name.value == document.name.value
    assert fetched.chunk_count == 2
    assert fetched.chunks is None  # a plain read never loads chunk contents back
    with uow:
        assert len(_chunk_rows(repo, uow, document.id)) == 2


def test_get_by_wrong_owner_returns_none(uow: SqlAlchemyUnitOfWork) -> None:
    owner_repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("user-1"))
    document = make_document_with_chunks(owner="user-1")
    with uow:
        owner_repo.add(document)

    other_repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("someone-else"))
    with uow:
        fetched = other_repo.get(document.id)
    assert fetched is None


def test_update_rename_only_leaves_chunks_untouched(uow: SqlAlchemyUnitOfWork) -> None:
    repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("user-1"))
    document = make_document_with_chunks(owner="user-1", name="Original.pdf", chunk_count=2)
    with uow:
        repo.add(document)

    with uow:
        fetched = repo.get(document.id, lock=True)
        assert fetched is not None
        assert fetched.chunks is None  # matches ReplaceDocumentUseCase's real pattern
        fetched.rename(DocumentName("Renamed.pdf"))
        repo.update(fetched)

    with uow:
        refetched = repo.get(document.id)
        assert refetched is not None
        assert refetched.name.value == "Renamed.pdf"
        assert refetched.chunk_count == 2
        assert len(_chunk_rows(repo, uow, document.id)) == 2


def test_update_replaces_chunks_when_given(uow: SqlAlchemyUnitOfWork) -> None:
    repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("user-1"))
    document = make_document_with_chunks(owner="user-1", chunk_count=2)
    with uow:
        repo.add(document)

    new_chunks = [make_chunk(document_id=document.id, index=i) for i in range(3)]
    with uow:
        fetched = repo.get(document.id, lock=True)
        assert fetched is not None
        fetched.replace_content(MimeType("text/plain"), new_chunks)
        repo.update(fetched)

    with uow:
        refetched = repo.get(document.id)
        assert refetched is not None
        assert refetched.mime_type.value == "text/plain"
        assert refetched.chunk_count == 3
        assert len(_chunk_rows(repo, uow, document.id)) == 3


def test_update_by_wrong_owner_raises_not_found(uow: SqlAlchemyUnitOfWork) -> None:
    """The RLS-bound `WHERE id = ...` matches 0 rows for a transaction bound to a
    different owner — proving the block is Postgres's, not a pre-check the caller
    could have skipped (§8.0)."""
    victim_repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("victim"))
    victim_document = make_document_with_chunks(owner="victim", name="Original.pdf")
    with uow:
        victim_repo.add(victim_document)

    forged = Document.from_repo(
        id=victim_document.id,
        owner=OwnerSubject("attacker"),
        name=DocumentName("Hacked.pdf"),
        mime_type=victim_document.mime_type,
        chunk_count=victim_document.chunk_count,
        created_at=victim_document.created_at,
        updated_at=victim_document.updated_at,
    )
    attacker_repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("attacker"))
    with pytest.raises(NotFoundError), uow:
        attacker_repo.update(forged)

    with uow:
        fetched = victim_repo.get(victim_document.id)
    assert fetched is not None
    assert fetched.name.value == "Original.pdf"


def test_delete_by_wrong_owner_raises_not_found(uow: SqlAlchemyUnitOfWork) -> None:
    owner_repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("user-1"))
    document = make_document_with_chunks(owner="user-1")
    with uow:
        owner_repo.add(document)

    other_repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("someone-else"))
    with pytest.raises(NotFoundError), uow:
        other_repo.delete(document.id)

    with uow:
        fetched = owner_repo.get(document.id)
    assert fetched is not None


def test_delete_by_owner_removes_it_and_cascades_chunks(uow: SqlAlchemyUnitOfWork) -> None:
    repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("user-1"))
    document = make_document_with_chunks(owner="user-1", chunk_count=2)
    with uow:
        repo.add(document)
        repo.delete(document.id)

    with uow:
        fetched = repo.get(document.id)
        assert len(_chunk_rows(repo, uow, document.id)) == 0
    assert fetched is None


def test_lock_true_takes_a_row_lock(uow: SqlAlchemyUnitOfWork) -> None:
    """Smoke test: `lock=True` must not error and must still return the row —
    concurrent-blocking behavior itself needs two connections and is exercised at the
    use-case level (test_replace_document.py's retry tests), not duplicated here."""
    repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("user-1"))
    document = make_document_with_chunks(owner="user-1")
    with uow:
        repo.add(document)
    with uow:
        fetched = repo.get(document.id, lock=True)
    assert fetched is not None


def test_cross_owner_row_is_invisible_even_via_raw_sql(uow: SqlAlchemyUnitOfWork) -> None:
    """Proves the block is Postgres RLS, not something living in the repo's own code:
    even a raw SQL SELECT bypassing every repo method entirely cannot see another
    owner's row once the transaction is bound to a different owner (§8.0)."""
    victim_repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("victim"))
    document = make_document_with_chunks(owner="victim")
    with uow:
        victim_repo.add(document)

    attacker_repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("attacker"))
    with uow:
        attacker_repo._bind_owner()  # bind only — then query raw SQL, not through get()
        assert uow.active_connection is not None
        row = (
            uow.active_connection.execute(
                schema.documents.select().where(schema.documents.c.id == document.id)
            )
            .mappings()
            .one_or_none()
        )
    assert row is None


def test_unbound_transaction_sees_no_rows(uow: SqlAlchemyUnitOfWork) -> None:
    """Fails closed: a transaction that never binds an owner sees nothing at all, not
    everything — the safe failure mode if some future code path forgot to bind (§8.0)."""
    owner_repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("victim"))
    document = make_document_with_chunks(owner="victim")
    with uow:
        owner_repo.add(document)

    with uow:
        assert uow.active_connection is not None
        rows = uow.active_connection.execute(schema.documents.select()).mappings().all()
    assert rows == []


def test_superuser_connection_bypasses_rls(uow: SqlAlchemyUnitOfWork, superuser_dsn: str) -> None:
    """The one thing RLS cannot close (§8.0, no `FORCE` closes this): a true
    superuser connection sees every row regardless of policy. This is why
    integration tests run as the unprivileged `rag_documents_app` role (conftest.py)
    — proving the boundary is real, not assumed, and confirming why it matters that
    the deployed app role must never be a superuser."""
    owner_repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("victim"))
    document = make_document_with_chunks(owner="victim")
    with uow:
        owner_repo.add(document)

    engine = create_engine(superuser_dsn)
    with engine.connect() as conn:
        # No SET LOCAL app.current_owner at all — a superuser doesn't need one.
        row = (
            conn.execute(schema.documents.select().where(schema.documents.c.id == document.id))
            .mappings()
            .one_or_none()
        )
    engine.dispose()
    assert row is not None


def test_with_check_violation_raises_integrity_error(uow: SqlAlchemyUnitOfWork) -> None:
    """Empirically confirms the claimed mapping: a genuine RLS `WITH CHECK` failure
    raises `psycopg.errors.InsufficientPrivilege`, and `translate_db_errors()` turns
    that into `IntegrityError` — deliberately bypasses `_add_impl`'s own owner guard
    (raw SQL, not `repo.add()`) to reach the DB-level backstop directly, since the
    guard makes this unreachable through the repo's public API (§8.0)."""
    repo = SqlAlchemyDocumentsRepo(uow, OwnerSubject("user-1"))
    document = make_document_with_chunks(owner="user-1")
    with pytest.raises(IntegrityError), uow:
        repo._bind_owner()  # transaction bound to "user-1"
        with translate_db_errors():
            repo._connection().execute(
                insert(schema.documents).values(
                    id=document.id,
                    owner_subject="someone-else",  # mismatched vs. the bound owner
                    name=document.name.value,
                    mime_type=document.mime_type.value,
                    chunk_count=document.chunk_count,
                    created_at=document.created_at,
                    updated_at=document.updated_at,
                )
            )
