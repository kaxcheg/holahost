"""create usage_records

Revision ID: f164b34680c6
Revises:
Create Date: 2026-09-27 19:54:03.076965

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f164b34680c6"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("downgraded", sa.Boolean(), nullable=False),
        sa.Column("failed_over", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name=op.f("ck_usage_records_tokens_non_negative"),
        ),
        sa.CheckConstraint("latency_ms >= 0", name=op.f("ck_usage_records_latency_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_records")),
    )
    op.create_index(
        op.f("ix_usage_records_client_id_created_at"), "usage_records", ["client_id", "created_at"]
    )
    op.create_index(
        op.f("ix_usage_records_provider_created_at"), "usage_records", ["provider", "created_at"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_usage_records_provider_created_at"), table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_client_id_created_at"), table_name="usage_records")
    op.drop_table("usage_records")
