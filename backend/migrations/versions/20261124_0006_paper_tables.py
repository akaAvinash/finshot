"""Paper trading tables, and automatic checks for existing strategy drafts.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-24

paper_trades and paper_events are append-only (UPDATE is rejected by a
trigger; DELETE stays possible so deleting a user can cascade).

Existing drafts are re-evaluated by the automatic rules of contract 0.7.0.
The thresholds and the symbol-to-instrument map are frozen copies of
app/strategies/rules.py and the demo instruments as of this revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_paper_events_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_events")),
        sa.UniqueConstraint("seq", name=op.f("uq_paper_events_seq")),
    )
    op.create_index("ix_paper_events_user_id_seq", "paper_events", ["user_id", "seq"], unique=False)
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("replay", sa.Integer(), nullable=False),
        sa.Column("instrument", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("limit_paise", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("side IN ('Buy', 'Sell')", name=op.f("ck_paper_orders_side_valid")),
        sa.CheckConstraint(
            "status IN ('queued', 'filled', 'cancelled')", name=op.f("ck_paper_orders_status_valid")
        ),
        sa.CheckConstraint("limit_paise >= 0", name=op.f("ck_paper_orders_limit_nonnegative")),
        sa.CheckConstraint("quantity >= 1", name=op.f("ck_paper_orders_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_paper_orders_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_orders")),
        sa.UniqueConstraint("seq", name=op.f("uq_paper_orders_seq")),
    )
    op.create_index("ix_paper_orders_user_id_seq", "paper_orders", ["user_id", "seq"], unique=False)
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("replay", sa.Integer(), nullable=False),
        sa.Column("instrument", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("fill_paise", sa.BigInteger(), nullable=False),
        sa.Column("fees_paise", sa.BigInteger(), nullable=False),
        sa.Column("pnl_paise", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reason IN ('entry', 'signal-exit', 'stop-loss', 'end-of-replay')",
            name=op.f("ck_paper_trades_reason_valid"),
        ),
        sa.CheckConstraint("side IN ('Buy', 'Sell')", name=op.f("ck_paper_trades_side_valid")),
        sa.CheckConstraint("fees_paise >= 0", name=op.f("ck_paper_trades_fees_nonnegative")),
        sa.CheckConstraint("fill_paise >= 1", name=op.f("ck_paper_trades_fill_positive")),
        sa.CheckConstraint("quantity >= 1", name=op.f("ck_paper_trades_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_paper_trades_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_trades")),
        sa.UniqueConstraint("seq", name=op.f("uq_paper_trades_seq")),
    )
    op.create_index("ix_paper_trades_user_id_seq", "paper_trades", ["user_id", "seq"], unique=False)
    op.create_table(
        "paper_accounts",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("engine", sa.String(length=16), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=True),
        sa.Column(
            "version_parameters",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("instrument_id", sa.String(length=64), nullable=True),
        sa.Column("replay", sa.Integer(), nullable=False),
        sa.Column("capital_paise", sa.BigInteger(), nullable=False),
        sa.Column("cash_paise", sa.BigInteger(), nullable=False),
        sa.Column("position_quantity", sa.BigInteger(), nullable=False),
        sa.Column("position_entry_paise", sa.BigInteger(), nullable=True),
        sa.Column("position_stop_paise", sa.BigInteger(), nullable=True),
        sa.Column("position_fees_paise", sa.BigInteger(), nullable=False),
        sa.Column("sessions_done", sa.Integer(), nullable=False),
        sa.Column("sessions_total", sa.Integer(), nullable=False),
        sa.Column("finished", sa.Boolean(), nullable=False),
        sa.Column("session_pnl_paise", sa.BigInteger(), nullable=False),
        sa.Column("session_fills", sa.Integer(), nullable=False),
        sa.Column("last_tick_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "engine <> 'running' OR NOT finished", name=op.f("ck_paper_accounts_running_unfinished")
        ),
        sa.CheckConstraint(
            "engine IN ('idle', 'running', 'halted')", name=op.f("ck_paper_accounts_engine_valid")
        ),
        sa.CheckConstraint(
            "(position_quantity = 0) = (position_entry_paise IS NULL) AND (position_quantity = 0) = (position_stop_paise IS NULL)",
            name=op.f("ck_paper_accounts_position_complete"),
        ),
        sa.CheckConstraint(
            "(strategy_id IS NULL) = (version_number IS NULL) AND (strategy_id IS NULL) = (version_parameters IS NULL) AND (strategy_id IS NULL) = (instrument_id IS NULL)",
            name=op.f("ck_paper_accounts_assignment_complete"),
        ),
        sa.CheckConstraint("cash_paise >= 0", name=op.f("ck_paper_accounts_cash_nonnegative")),
        sa.CheckConstraint(
            "position_quantity >= 0", name=op.f("ck_paper_accounts_position_nonnegative")
        ),
        sa.CheckConstraint(
            "session_fills >= 0", name=op.f("ck_paper_accounts_session_fills_nonnegative")
        ),
        sa.CheckConstraint(
            "sessions_done >= 0 AND sessions_done <= sessions_total",
            name=op.f("ck_paper_accounts_sessions_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name=op.f("fk_paper_accounts_strategy_id_strategies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_paper_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_paper_accounts")),
    )

    op.execute(
        """
        CREATE FUNCTION paper_ledger_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% rows are append-only', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    for table in ("paper_trades", "paper_events"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_no_update
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION paper_ledger_append_only()
            """
        )
    _reevaluate_drafts()


_TIER_LIMITS = {  # tier: (max positionSizeBps, max stopLossBps, min maxDrawdownBps)
    "low": (600, 100, -500),
    "medium": (1000, 200, -1000),
    "high": (1500, 300, -2000),
}
_INSTRUMENT_IDS = {
    "NIFTY 50": "NSE:NIFTY50",
    "BANKNIFTY": "NSE:BANKNIFTY",
    "FINNIFTY": "NSE:FINNIFTY",
    "RELIANCE": "NSE:RELIANCE",
    "HDFCBANK": "NSE:HDFCBANK",
    "SBIN": "NSE:SBIN",
}


def _case(column: str, values: dict[str, object]) -> str:
    whens = " ".join(f"WHEN '{key}' THEN {value!r}" for key, value in values.items())
    return f"CASE {column} {whens} END"


def _reevaluate_drafts() -> None:
    tier = "s.draft_parameters->>'risk_tier'"
    max_size = _case(tier, {k: v[0] for k, v in _TIER_LIMITS.items()})
    max_stop = _case(tier, {k: v[1] for k, v in _TIER_LIMITS.items()})
    min_drawdown = _case(tier, {k: v[2] for k, v in _TIER_LIMITS.items()})
    instrument = _case("s.draft_parameters->>'instrument'", _INSTRUMENT_IDS)
    # The interpolated values are the frozen constants above, not input.
    op.execute(
        f"""
        UPDATE strategies s SET draft_risk_review = CASE
            WHEN (s.draft_parameters->>'position_size_bps')::int <= {max_size}
             AND (s.draft_parameters->>'stop_loss_bps')::int <= {max_stop}
            THEN 'approved' ELSE 'rejected' END
        WHERE s.draft_parameters IS NOT NULL
        """  # noqa: S608
    )
    op.execute(
        f"""
        UPDATE strategies s SET draft_backtest = CASE
            WHEN jsonb_array_length(latest.result->'points') >= 10
             AND jsonb_array_length(latest.result->'trades') >= 1
             AND (latest.result->>'netPnlPaise')::bigint >= 0
             AND (latest.result->>'maxDrawdownBps')::int >= {min_drawdown}
            THEN 'passed' ELSE 'failed' END
        FROM (
            SELECT DISTINCT ON (r.strategy_id) r.strategy_id, r.result
            FROM backtest_runs r
            JOIN strategies s ON s.id = r.strategy_id
            WHERE r.status = 'completed'
              AND s.draft_parameters IS NOT NULL
              AND r.config->>'strategyId' = s.id::text || ':' || 'draft'
              AND r.parameters = s.draft_parameters
              AND r.config->>'instrumentId' = {instrument}
              AND (r.config->>'feeBps')::int >= 3
              AND (r.config->>'slippageBps')::int >= 5
            ORDER BY r.strategy_id, r.updated_at DESC, r.seq DESC
        ) latest
        WHERE s.id = latest.strategy_id
        """  # noqa: S608
    )


def downgrade() -> None:
    # Before 0006 nothing set the checks: drafts were unavailable/pending.
    op.execute(
        "UPDATE strategies SET draft_backtest = 'unavailable', draft_risk_review = 'pending'"
        " WHERE draft_parameters IS NOT NULL"
    )
    op.drop_table("paper_accounts")
    op.drop_index("ix_paper_trades_user_id_seq", table_name="paper_trades")
    op.drop_table("paper_trades")
    op.drop_index("ix_paper_orders_user_id_seq", table_name="paper_orders")
    op.drop_table("paper_orders")
    op.drop_index("ix_paper_events_user_id_seq", table_name="paper_events")
    op.drop_table("paper_events")
    op.execute("DROP FUNCTION paper_ledger_append_only()")
