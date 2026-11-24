"""Backtest runs table.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name=op.f("ck_backtest_runs_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'completed') = (result IS NOT NULL)",
            name=op.f("ck_backtest_runs_result_iff_completed"),
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (message IS NOT NULL)",
            name=op.f("ck_backtest_runs_message_iff_failed"),
        ),
        sa.CheckConstraint(
            "(status = 'queued') = (started_at IS NULL)",
            name=op.f("ck_backtest_runs_started_unless_queued"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_backtest_runs_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name="fk_backtest_runs_strategy_id_strategies",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_backtest_runs"),
        sa.UniqueConstraint("seq", name="uq_backtest_runs_seq"),
    )
    op.create_index("ix_backtest_runs_user_id_seq", "backtest_runs", ["user_id", "seq"])
    # The worker claims the oldest queued run; the run limit counts active runs.
    op.create_index(
        "ix_backtest_runs_active_seq",
        "backtest_runs",
        ["seq"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_table("backtest_runs")
