"""Advisory agent tables: agent_events, agent_runs and agent_worker.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-24

agent_events is append-only, like the paper ledger (it reuses the
paper_ledger_append_only() trigger function from 0006); DELETE stays possible
so deleting a user can cascade. Both tables start empty: the agent worker
evaluates existing paper accounts on its first pass, so no backfill is needed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.String(length=32), nullable=False),
        sa.Column("dedupe_key", sa.String(length=128), nullable=False),
        sa.Column("reason_code", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("link_kind", sa.String(length=16), nullable=True),
        sa.Column("link_id", sa.String(length=64), nullable=True),
        sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "agent_id IN ('market-scanner', 'strategy-analyst', 'risk-explainer',"
            " 'execution-monitor')",
            name=op.f("ck_agent_events_agent_id_valid"),
        ),
        sa.CheckConstraint(
            "link_kind IS NULL OR link_kind IN ('paper-trade', 'paper-order', 'paper-replay')",
            name=op.f("ck_agent_events_link_kind_valid"),
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning')", name=op.f("ck_agent_events_severity_valid")
        ),
        sa.CheckConstraint(
            "(link_kind IS NULL) = (link_id IS NULL)",
            name=op.f("ck_agent_events_link_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_events")),
        sa.UniqueConstraint("seq", name=op.f("uq_agent_events_seq")),
        sa.UniqueConstraint(
            "user_id", "agent_id", "dedupe_key", name=op.f("uq_agent_events_dedupe")
        ),
    )
    op.create_index(
        "ix_agent_events_user_id_agent_id_seq",
        "agent_events",
        ["user_id", "agent_id", "seq"],
        unique=False,
    )
    op.create_index("ix_agent_events_user_id_seq", "agent_events", ["user_id", "seq"], unique=False)
    op.execute(
        "CREATE TRIGGER agent_events_no_update BEFORE UPDATE ON agent_events"
        " FOR EACH ROW EXECUTE FUNCTION paper_ledger_append_only()"
    )
    op.create_table(
        "agent_runs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_runs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_agent_runs")),
    )
    op.create_table(
        "agent_worker",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("pass_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_agent_worker_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_worker")),
    )


def downgrade() -> None:
    op.drop_table("agent_worker")
    op.drop_table("agent_runs")
    op.drop_table("agent_events")
