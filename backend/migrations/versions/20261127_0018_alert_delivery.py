"""Alert delivery by email, SMS and push (contract 0.13.0).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-27

alert_channel_settings: per user and channel, enabled flag, minimum severity
and when it was last enabled. alert_deliveries: one row per alert (or test)
and channel with its status; alert_id is set to NULL when the alert is purged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANNEL = "channel IN ('email', 'sms', 'push')"


def upgrade() -> None:
    op.create_table(
        "alert_channel_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("min_severity", sa.String(8), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_CHANNEL, name=op.f("ck_alert_channel_settings_channel_valid")),
        sa.CheckConstraint(
            "min_severity IN ('critical', 'warning', 'info')",
            name=op.f("ck_alert_channel_settings_min_severity_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_alert_channel_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "channel", name=op.f("pk_alert_channel_settings")),
    )
    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("status_reason", sa.String(32), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("destination_masked", sa.String(64), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_CHANNEL, name=op.f("ck_alert_deliveries_channel_valid")),
        sa.CheckConstraint(
            "kind IN ('alert', 'test')", name=op.f("ck_alert_deliveries_kind_valid")
        ),
        sa.CheckConstraint(
            "kind = 'alert' OR alert_id IS NULL", name=op.f("ck_alert_deliveries_test_has_no_alert")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name=op.f("ck_alert_deliveries_status_valid"),
        ),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND 3", name=op.f("ck_alert_deliveries_attempts_range")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_alert_deliveries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"],
            ["alerts.id"],
            name=op.f("fk_alert_deliveries_alert_id_alerts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_deliveries")),
    )
    op.create_index(
        "uq_alert_deliveries_alert_channel",
        "alert_deliveries",
        ["alert_id", "channel"],
        unique=True,
        postgresql_where=sa.text("alert_id IS NOT NULL"),
    )
    op.create_index(
        "ix_alert_deliveries_user_id_created_at", "alert_deliveries", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_alert_deliveries_pending",
        "alert_deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    # The delivery worker looks for recent alerts.
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_alerts_created_at", table_name="alerts")
    op.drop_table("alert_deliveries")
    op.drop_table("alert_channel_settings")
