"""Alert tables (alerts, alert_preferences).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-25

alerts rows never change except acknowledged_at, which may go from null to a
time once; the alerts_acknowledge_only() trigger rejects any other UPDATE.
DELETE stays possible so deleting a user can cascade. Both tables start
empty: nothing is backfilled, so activity before this revision raises no
alert (the alert worker records broker connections that are already expired
on its first pass).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("environment", sa.String(length=8), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("link_kind", sa.String(length=16), nullable=True),
        sa.Column("link_id", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "severity IN ('critical', 'warning', 'info')",
            name=op.f("ck_alerts_severity_valid"),
        ),
        sa.CheckConstraint(
            "source IN ('paper', 'brokers', 'agents', 'security')",
            name=op.f("ck_alerts_source_valid"),
        ),
        sa.CheckConstraint(
            "environment IS NULL OR environment IN ('PAPER', 'DEMO')",
            name=op.f("ck_alerts_environment_valid"),
        ),
        sa.CheckConstraint(
            "link_kind IS NULL OR link_kind IN"
            " ('paper-trade', 'paper-order', 'paper-replay', 'broker', 'session')",
            name=op.f("ck_alerts_link_kind_valid"),
        ),
        sa.CheckConstraint(
            "(link_kind IS NULL) = (link_id IS NULL)", name=op.f("ck_alerts_link_complete")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_alerts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        sa.UniqueConstraint("seq", name=op.f("uq_alerts_seq")),
        sa.UniqueConstraint("user_id", "dedupe_key", name=op.f("uq_alerts_dedupe")),
    )
    op.create_index("ix_alerts_user_id_seq", "alerts", ["user_id", "seq"])
    op.create_index(
        "ix_alerts_user_id_unread",
        "alerts",
        ["user_id", "severity"],
        postgresql_where=sa.text("acknowledged_at IS NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION alerts_acknowledge_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.acknowledged_at IS NOT NULL
               OR NEW.acknowledged_at IS NULL
               OR (NEW.id, NEW.seq, NEW.user_id, NEW.dedupe_key, NEW.kind, NEW.source,
                   NEW.severity, NEW.environment, NEW.title, NEW.message, NEW.link_kind,
                   NEW.link_id, NEW.occurred_at, NEW.created_at)
                  IS DISTINCT FROM
                  (OLD.id, OLD.seq, OLD.user_id, OLD.dedupe_key, OLD.kind, OLD.source,
                   OLD.severity, OLD.environment, OLD.title, OLD.message, OLD.link_kind,
                   OLD.link_id, OLD.occurred_at, OLD.created_at)
            THEN
                RAISE EXCEPTION 'alerts rows change only by a first acknowledgement'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER alerts_acknowledge_only
        BEFORE UPDATE ON alerts
        FOR EACH ROW EXECUTE FUNCTION alerts_acknowledge_only()
        """
    )
    op.create_table(
        "alert_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("warning", sa.Boolean(), nullable=False),
        sa.Column("info", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_alert_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_alert_preferences")),
    )


def downgrade() -> None:
    op.drop_table("alert_preferences")
    op.drop_table("alerts")
    op.execute("DROP FUNCTION alerts_acknowledge_only()")
