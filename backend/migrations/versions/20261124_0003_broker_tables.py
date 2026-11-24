"""Broker tables: broker_connections, broker_events (demo only).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("gen_random_uuid()")
_PROVIDER_CHECK = "provider IN ('zerodha', 'fyers')"


def upgrade() -> None:
    op.create_table(
        "broker_connections",
        sa.Column("id", sa.Uuid(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("environment", sa.String(length=8), server_default="DEMO", nullable=False),
        sa.Column("masked_account_id", sa.String(length=32), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_PROVIDER_CHECK, name=op.f("ck_broker_connections_provider_valid")),
        sa.CheckConstraint(
            "environment = 'DEMO'", name=op.f("ck_broker_connections_environment_demo")
        ),
        sa.CheckConstraint(
            "expires_at > connected_at", name=op.f("ck_broker_connections_expiry_after_connect")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_broker_connections_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_broker_connections"),
        sa.UniqueConstraint("user_id", "provider", name="uq_broker_connections_user_id_provider"),
    )
    op.create_table(
        "broker_events",
        sa.Column("id", sa.Uuid(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(_PROVIDER_CHECK, name=op.f("ck_broker_events_provider_valid")),
        sa.CheckConstraint(
            "action IN ('connect', 'reconnect', 'sync', 'disconnect')",
            name=op.f("ck_broker_events_action_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_broker_events_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_broker_events"),
        sa.UniqueConstraint("seq", name="uq_broker_events_seq"),
    )
    op.create_index("ix_broker_events_user_id_seq", "broker_events", ["user_id", "seq"])


def downgrade() -> None:
    op.drop_table("broker_events")
    op.drop_table("broker_connections")
