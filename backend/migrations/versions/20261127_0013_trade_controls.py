"""Paper Trade Controls.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-27

trade_controls: one row per user who has saved controls (no row = defaults,
revision 0). trade_control_changes: append-only history, one row per applied
save with the changed fields' old and new values.
paper_accounts: the last session's peak realised P&L and loss streak (for the
profit cap and consecutive-loss limit) and the open position's take-profit
target. paper_trades.reason gains `take-profit`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_REASONS = "reason IN ('entry', 'signal-exit', 'stop-loss', 'end-of-replay')"
NEW_REASONS = "reason IN ('entry', 'signal-exit', 'stop-loss', 'take-profit', 'end-of-replay')"


def upgrade() -> None:
    op.create_table(
        "trade_controls",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("loss_limit_paise", sa.BigInteger(), nullable=False),
        sa.Column("trade_limit", sa.Integer(), nullable=False),
        sa.Column("profit_limit_paise", sa.BigInteger(), nullable=True),
        sa.Column("max_consecutive_losses", sa.Integer(), nullable=False),
        sa.Column("stop_loss_bps", sa.Integer(), nullable=True),
        sa.Column("take_profit_bps", sa.Integer(), nullable=True),
        sa.Column("max_risk_per_trade_paise", sa.BigInteger(), nullable=False),
        sa.Column("max_position_size_bps", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_trade_controls_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_trade_controls")),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_trade_controls_revision_positive")),
        sa.CheckConstraint("loss_limit_paise >= 1", name=op.f("ck_trade_controls_loss_positive")),
        sa.CheckConstraint("trade_limit >= 1", name=op.f("ck_trade_controls_trades_positive")),
        sa.CheckConstraint(
            "profit_limit_paise IS NULL OR profit_limit_paise >= 1",
            name=op.f("ck_trade_controls_profit_positive"),
        ),
        sa.CheckConstraint(
            "max_consecutive_losses >= 0", name=op.f("ck_trade_controls_streak_nonnegative")
        ),
        sa.CheckConstraint(
            "stop_loss_bps IS NULL OR stop_loss_bps BETWEEN 1 AND 9999",
            name=op.f("ck_trade_controls_stop_range"),
        ),
        sa.CheckConstraint(
            "take_profit_bps IS NULL OR take_profit_bps BETWEEN 1 AND 10000",
            name=op.f("ck_trade_controls_target_range"),
        ),
        sa.CheckConstraint(
            "max_risk_per_trade_paise >= 1", name=op.f("ck_trade_controls_risk_positive")
        ),
        sa.CheckConstraint(
            "max_position_size_bps BETWEEN 1 AND 10000", name=op.f("ck_trade_controls_size_range")
        ),
    )
    op.create_table(
        "trade_control_changes",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fields", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_trade_control_changes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "revision", name=op.f("pk_trade_control_changes")),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck_trade_control_changes_revision_positive")
        ),
    )
    op.add_column(
        "paper_accounts",
        sa.Column("session_peak_pnl_paise", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "paper_accounts",
        sa.Column("session_loss_streak", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "paper_accounts", sa.Column("position_target_paise", sa.BigInteger(), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_paper_accounts_target_needs_position"),
        "paper_accounts",
        "position_target_paise IS NULL OR position_quantity > 0",
    )
    op.drop_constraint(op.f("ck_paper_trades_reason_valid"), "paper_trades", type_="check")
    op.create_check_constraint(op.f("ck_paper_trades_reason_valid"), "paper_trades", NEW_REASONS)


def downgrade() -> None:
    op.execute("DELETE FROM paper_trades WHERE reason = 'take-profit'")
    op.drop_constraint(op.f("ck_paper_trades_reason_valid"), "paper_trades", type_="check")
    op.create_check_constraint(op.f("ck_paper_trades_reason_valid"), "paper_trades", OLD_REASONS)
    op.drop_constraint(
        op.f("ck_paper_accounts_target_needs_position"), "paper_accounts", type_="check"
    )
    op.drop_column("paper_accounts", "position_target_paise")
    op.drop_column("paper_accounts", "session_loss_streak")
    op.drop_column("paper_accounts", "session_peak_pnl_paise")
    op.drop_table("trade_control_changes")
    op.drop_table("trade_controls")
