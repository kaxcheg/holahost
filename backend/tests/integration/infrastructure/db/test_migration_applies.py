from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from infrastructure.db.sqlalchemy import schema
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork


@pytest.mark.integration
def test_all_tables_created(uow: PostgresUnitOfWork) -> None:
    with uow.transaction():
        rows = uow.connection.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        ).fetchall()
    names = {r[0] for r in rows}
    assert {"guidebooks", "leads", "chunks", "rate_limit_counters", "sample_budget"} <= names


@pytest.mark.integration
def test_partial_unique_magic_link_index_present(uow: PostgresUnitOfWork) -> None:
    with uow.transaction():
        rows = uow.connection.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = 'leads'")
        ).fetchall()
    assert "ix_leads_magic_link_unique" in {r[0] for r in rows}


@pytest.mark.integration
def test_db_schema_matches_metadata(uow: PostgresUnitOfWork) -> None:
    # The migration materialises infrastructure/db/schema.py; this guards that the live DB columns
    # match that single-source metadata (the DDL guard, since Alembic autogenerate is candidate-only).
    with uow.transaction():
        inspector = inspect(uow.connection)
        for table in schema.metadata.tables.values():
            db_columns = {col["name"] for col in inspector.get_columns(table.name)}
            metadata_columns = {col.name for col in table.columns}
            assert metadata_columns == db_columns, table.name
