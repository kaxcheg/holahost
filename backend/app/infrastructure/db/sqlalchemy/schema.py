"""Single source of truth for the relational schema (spec §4).

These ``Table`` objects are the ONE place the persistence schema is declared: they drive both the
Core queries in the repository adapters and the Alembic migrations (``env.py`` exposes ``metadata``
as ``target_metadata``; the initial migration materialises it via ``metadata.create_all``). The
domain entities stay persistence-ignorant — the column↔attribute bridge (and value-object
conversion) lives in each adapter's in-module Data Mapper (``_to_values`` / ``_from_row``), not here
and not on the entities.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA, TIMESTAMP, UUID

metadata = MetaData()

guidebooks = Table(
    "guidebooks",
    metadata,
    Column("guidebook_id", UUID(as_uuid=True), primary_key=True),
    Column("name", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column(
        "last_accessed_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    ),
    Column("ip_hash", Text, nullable=False),
)

leads = Table(
    "leads",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("email", Text, nullable=False, unique=True),
    Column("magic_link", Text, nullable=True),
    Column("captured_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("last_seen_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    Column("flow", Text, nullable=False),
    Column(
        "guidebook_id",
        UUID(as_uuid=True),
        ForeignKey("guidebooks.guidebook_id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("ip_hash", Text, nullable=False),
    Column("ua_short", Text, nullable=True),
)

chunks = Table(
    "chunks",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "guidebook_id",
        UUID(as_uuid=True),
        ForeignKey("guidebooks.guidebook_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("ordinal", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("page", Integer, nullable=True),
    Column("embedding", BYTEA, nullable=False),
)

rate_limit_counters = Table(
    "rate_limit_counters",
    metadata,
    Column("scope", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("window_start", TIMESTAMP(timezone=True), nullable=False),
    Column("counter", Integer, nullable=False, server_default=text("0")),
    PrimaryKeyConstraint("scope", "subject", "window_start"),
)

sample_budget = Table(
    "sample_budget",
    metadata,
    Column("date", Date, primary_key=True),
    Column("output_tokens_used", BigInteger, nullable=False, server_default=text("0")),
    Column("dollars_spent_est", Numeric(10, 4), nullable=False, server_default=text("0")),
)

# §4.6 indexes (partial indexes are persistence-only facts — they have no place on the domain).
# Each is consulted only by the Postgres query planner; the comment names the access path it serves.

# Enforces uniqueness of an *active* magic link AND serves the token lookups
# PostgresLeadsRepo.get_by_magic_link / get_by_magic_link_for_update (WHERE magic_link = …).
Index(
    "ix_leads_magic_link_unique",
    leads.c.magic_link,
    unique=True,
    postgresql_where=leads.c.magic_link.isnot(None),
)
# Serves PostgresLeadsRepo.list_expired: WHERE magic_link IS NOT NULL AND last_seen_at < threshold
# ORDER BY last_seen_at — the cleanup-candidate scan (§9.6). Partial: only rows with a live token.
Index(
    "ix_leads_last_seen_active",
    leads.c.last_seen_at,
    postgresql_where=leads.c.magic_link.isnot(None),
)
# Serves the FK ``guidebook_id`` ON DELETE SET NULL reverse scan: when a guidebook is deleted,
# Postgres must find the leads referencing it to null the column (§7.5 / §4.3).
Index(
    "ix_leads_guidebook_id",
    leads.c.guidebook_id,
    postgresql_where=leads.c.guidebook_id.isnot(None),
)
# Serves PostgresChunksRepo.list_for_guidebook (WHERE guidebook_id = … ORDER BY ordinal) and the
# FK ON DELETE CASCADE scan that removes a deleted guidebook's chunks (§4.3 / §9.4).
Index("ix_chunks_guidebook_id", chunks.c.guidebook_id)
# Serves PostgresRateLimiter.cleanup_old_windows (DELETE WHERE window_start < threshold, §9.7).
Index("ix_rate_limit_window_start", rate_limit_counters.c.window_start)
