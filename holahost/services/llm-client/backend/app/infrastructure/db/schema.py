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

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
)

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

# Every constraint spelled out: a CHECK in the schema is an invariant the database enforces
# whatever code path wrote the row, where the same rule in an entity holds only for rows that went
# through it.

usage_records = Table(
    "usage_records",
    metadata,
    Column("id", Uuid, primary_key=True),
    # X-Request-ID: correlation with the logs, not the identity — two paid generations may share it.
    Column("request_id", Text, nullable=False),
    Column("client_id", Text, nullable=False),
    Column("subject", Text, nullable=False),
    # Strings, not references: a model removed from the registry stays readable in its history.
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("latency_ms", Integer, nullable=False),
    Column("downgraded", Boolean, nullable=False),
    Column("failed_over", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens_non_negative"),
    CheckConstraint("latency_ms >= 0", name="latency_non_negative"),
)
"""The usage log: one row per provider call whose usage the provider confirmed — an answer or a
content refusal. Append-only, and the source of every budget: spend in a window is an aggregate
over it."""

# The two dimensions spend is asked about — per caller and per provider — which are also the two the
# budget check aggregates over.
Index(
    "ix_usage_records_client_id_created_at", usage_records.c.client_id, usage_records.c.created_at
)
Index("ix_usage_records_provider_created_at", usage_records.c.provider, usage_records.c.created_at)
