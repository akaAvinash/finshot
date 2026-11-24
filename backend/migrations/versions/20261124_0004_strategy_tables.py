"""Strategy tables: strategies, strategy_versions (immutable).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column("id", sa.Uuid(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("draft_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("draft_backtest", sa.String(length=16), nullable=True),
        sa.Column("draft_risk_review", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused')", name=op.f("ck_strategies_status_valid")
        ),
        sa.CheckConstraint(
            "draft_backtest IS NULL OR draft_backtest IN ('passed', 'failed', 'unavailable')",
            name=op.f("ck_strategies_draft_backtest_valid"),
        ),
        sa.CheckConstraint(
            "draft_risk_review IS NULL OR draft_risk_review IN ('approved', 'rejected', 'pending')",
            name=op.f("ck_strategies_draft_risk_review_valid"),
        ),
        sa.CheckConstraint(
            "(draft_parameters IS NULL) = (draft_backtest IS NULL)"
            " AND (draft_parameters IS NULL) = (draft_risk_review IS NULL)",
            name=op.f("ck_strategies_draft_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_strategies_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategies"),
        sa.UniqueConstraint("seq", name="uq_strategies_seq"),
    )
    op.create_index("ix_strategies_user_id_seq", "strategies", ["user_id", "seq"])
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.Uuid(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parameters_hash", sa.String(length=64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("number >= 1", name=op.f("ck_strategy_versions_number_positive")),
        sa.CheckConstraint(
            "parameters_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_strategy_versions_hash_format")
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name="fk_strategy_versions_strategy_id_strategies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_strategy_versions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_versions"),
        sa.UniqueConstraint(
            "strategy_id", "number", name="uq_strategy_versions_strategy_id_number"
        ),
    )
    op.create_index("ix_strategy_versions_user_id", "strategy_versions", ["user_id"])
    # Versions are immutable once written. DELETE stays possible so that
    # deleting a user (or a strategy) can cascade.
    op.execute(
        """
        CREATE FUNCTION strategy_versions_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'strategy_versions rows are immutable'
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER strategy_versions_no_update
        BEFORE UPDATE ON strategy_versions
        FOR EACH ROW EXECUTE FUNCTION strategy_versions_immutable()
        """
    )


def downgrade() -> None:
    op.drop_table("strategy_versions")
    op.execute("DROP FUNCTION strategy_versions_immutable()")
    op.drop_table("strategies")
