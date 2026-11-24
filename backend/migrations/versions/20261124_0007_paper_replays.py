"""Record the strategy version of each paper replay, for reports.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-24

paper_replays is append-only, like paper_trades and paper_events (it reuses
the paper_ledger_append_only() trigger function from 0006).

Backfill: each paper account's current replay is recorded from the account's
pinned version. Earlier replays were not recorded before this revision, so
their fills stay unattributed (reports show them with `strategy: null`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_replays",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("replay", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("strategy_name", sa.String(length=64), nullable=False),
        sa.Column("instrument_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("replay >= 1", name=op.f("ck_paper_replays_replay_positive")),
        sa.CheckConstraint("version_number >= 1", name=op.f("ck_paper_replays_version_positive")),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name=op.f("fk_paper_replays_strategy_id_strategies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_paper_replays_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "replay", name=op.f("pk_paper_replays")),
    )
    op.execute(
        "CREATE TRIGGER paper_replays_no_update BEFORE UPDATE ON paper_replays"
        " FOR EACH ROW EXECUTE FUNCTION paper_ledger_append_only()"
    )
    op.execute(
        "INSERT INTO paper_replays"
        " (user_id, replay, strategy_id, version_number, strategy_name, instrument_id,"
        " created_at)"
        " SELECT user_id, replay, strategy_id, version_number,"
        " version_parameters ->> 'name', instrument_id, updated_at"
        " FROM paper_accounts WHERE replay >= 1 AND strategy_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_table("paper_replays")
