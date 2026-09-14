"""The service's tables, and the one `MetaData` Alembic shares with them.

One `MetaData` rather than two declarations: `migrations/env.py` passes this object as
`target_metadata`, so `alembic revision --autogenerate` compares the database against the
same definition the repositories query.

The naming convention is set rather than left to Postgres. Without it an index or a
constraint created by autogenerate gets whatever name the backend invents, which differs
between a table created by a migration and the same table created from `metadata.create_all`
in a test — and a later migration that wants to drop one has no name to use.
"""

from __future__ import annotations

from sqlalchemy import MetaData

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

# Tables go here, each with its constraints spelled out — a CHECK in the schema is an
# invariant the database enforces regardless of which code path wrote the row, where the
# same rule in an entity holds only for rows that went through it.
