"""Data retention settings and purge watermark (contract 0.13.0).

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-27

data_retention: per-user period (null = server default), the latest purge
cutoff applied (`purged_through`) and the last purge that deleted anything.
Also indexes alerts and agent_events by (user_id, created_at) for the purge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_retention",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_purge_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_purge_counts", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "retention_days IS NULL OR retention_days BETWEEN 1 AND 36500",
            name=op.f("ck_data_retention_days_range"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_data_retention_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_data_retention")),
    )
    op.create_index("ix_alerts_user_id_created_at", "alerts", ["user_id", "created_at"])
    op.create_index("ix_agent_events_user_id_created_at", "agent_events", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_events_user_id_created_at", table_name="agent_events")
    op.drop_index("ix_alerts_user_id_created_at", table_name="alerts")
    op.drop_table("data_retention")
