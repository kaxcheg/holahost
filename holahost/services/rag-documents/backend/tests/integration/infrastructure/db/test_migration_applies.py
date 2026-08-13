from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

pytestmark = pytest.mark.integration


def test_tables_and_extension_exist(pg_dsn: str) -> None:
    engine = create_engine(pg_dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.connect() as conn:
        installed = conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
        assert installed == "vector"
        inspector = inspect(engine)
        assert {"documents", "chunks"} <= set(inspector.get_table_names())
    engine.dispose()


def test_row_level_security_enabled_and_forced(pg_dsn: str) -> None:
    engine = create_engine(pg_dsn.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.connect() as conn:
        for table in ("documents", "chunks"):
            row = conn.execute(
                text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"),
                {"t": table},
            ).one()
            assert row.relrowsecurity is True, f"{table}: RLS not enabled"
            assert row.relforcerowsecurity is True, f"{table}: RLS not forced"
    engine.dispose()
