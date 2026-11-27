"""Broker connections v2 (contract 0.11.0).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-27

broker_connections: the provider is an open id (format check, not a closed
list), one user may hold several connections to a provider (unique per
provider account), and a connection keeps the provider's account reference,
the reason an authorization was invalidated, and the last synced portfolio.
broker_events: events carry the `connectionId` (kept after a disconnect) and
may be `expire`. broker_authorizations: pending two-step authorizations,
bound to the session that started them. alerts.link_kind gains
`broker-connection` (and is widened to hold it).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_DEFAULT = sa.text("gen_random_uuid()")
_PROVIDER_FORMAT = "provider ~ '^[a-z][a-z0-9_-]{1,31}$'"
_OLD_PROVIDERS = "provider IN ('zerodha', 'fyers')"
_OLD_LINKS = (
    "link_kind IS NULL OR link_kind IN"
    " ('paper-trade', 'paper-order', 'paper-replay', 'broker', 'session')"
)
_NEW_LINKS = (
    "link_kind IS NULL OR link_kind IN"
    " ('paper-trade', 'paper-order', 'paper-replay', 'broker', 'broker-connection', 'session')"
)
_OLD_ACTIONS = "action IN ('connect', 'reconnect', 'sync', 'disconnect')"
_NEW_ACTIONS = "action IN ('connect', 'reconnect', 'sync', 'disconnect', 'expire')"


def upgrade() -> None:
    # --- broker_connections
    op.add_column("broker_connections", sa.Column("account_ref", sa.String(64), nullable=True))
    op.execute("UPDATE broker_connections SET account_ref = masked_account_id")
    op.alter_column("broker_connections", "account_ref", nullable=False)
    op.add_column("broker_connections", sa.Column("status_reason", sa.String(16), nullable=True))
    op.add_column("broker_connections", sa.Column("portfolio", postgresql.JSONB(none_as_null=True)))
    op.alter_column("broker_connections", "provider", type_=sa.String(32))
    op.drop_constraint(op.f("ck_broker_connections_provider_valid"), "broker_connections")
    op.create_check_constraint(
        op.f("ck_broker_connections_provider_format"), "broker_connections", _PROVIDER_FORMAT
    )
    op.create_check_constraint(
        op.f("ck_broker_connections_status_reason_valid"),
        "broker_connections",
        "status_reason IS NULL OR status_reason = 'AUTH_INVALIDATED'",
    )
    op.drop_constraint(op.f("uq_broker_connections_user_id_provider"), "broker_connections")
    op.create_unique_constraint(
        op.f("uq_broker_connections_account"),
        "broker_connections",
        ["user_id", "provider", "account_ref"],
    )

    # --- broker_events
    op.add_column("broker_events", sa.Column("connection_id", sa.Uuid(), nullable=True))
    op.execute(
        "UPDATE broker_events e SET connection_id = c.id FROM broker_connections c"
        " WHERE c.user_id = e.user_id AND c.provider = e.provider"
    )
    op.execute(
        "UPDATE broker_events e SET connection_id = g.cid FROM ("
        " SELECT user_id, provider, gen_random_uuid() AS cid FROM"
        " (SELECT DISTINCT user_id, provider FROM broker_events"
        "  WHERE connection_id IS NULL) d) g"
        " WHERE e.connection_id IS NULL AND g.user_id = e.user_id AND g.provider = e.provider"
    )
    op.alter_column("broker_events", "connection_id", nullable=False)
    op.alter_column("broker_events", "provider", type_=sa.String(32))
    op.drop_constraint(op.f("ck_broker_events_provider_valid"), "broker_events")
    op.create_check_constraint(
        op.f("ck_broker_events_provider_format"), "broker_events", _PROVIDER_FORMAT
    )
    op.drop_constraint(op.f("ck_broker_events_action_valid"), "broker_events")
    op.create_check_constraint(op.f("ck_broker_events_action_valid"), "broker_events", _NEW_ACTIONS)
    # One expiry event per connection and expiry time, even with two workers.
    op.create_index(
        "uq_broker_events_expire",
        "broker_events",
        ["connection_id", "at"],
        unique=True,
        postgresql_where=sa.text("action = 'expire'"),
    )

    # --- broker_authorizations
    op.create_table(
        "broker_authorizations",
        sa.Column("id", sa.Uuid(), server_default=_UUID_DEFAULT, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_PROVIDER_FORMAT, name=op.f("ck_broker_authorizations_provider_format")),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_broker_authorizations_expiry_after_start")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_broker_authorizations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broker_authorizations")),
        sa.UniqueConstraint("state_hash", name=op.f("uq_broker_authorizations_state_hash")),
    )

    # --- alerts: the new link kind (alerts rows are append-only, a column
    # widening and a check swap touch no row).
    op.alter_column("alerts", "link_kind", type_=sa.String(24))
    op.drop_constraint(op.f("ck_alerts_link_kind_valid"), "alerts")
    op.create_check_constraint(op.f("ck_alerts_link_kind_valid"), "alerts", _NEW_LINKS)


def downgrade() -> None:
    # Alerts that link to a connection lose the link (their text stays). The
    # append-only trigger is off for this one statement.
    op.execute("ALTER TABLE alerts DISABLE TRIGGER USER")
    op.execute(
        "UPDATE alerts SET link_kind = NULL, link_id = NULL WHERE link_kind = 'broker-connection'"
    )
    op.execute("ALTER TABLE alerts ENABLE TRIGGER USER")
    op.drop_constraint(op.f("ck_alerts_link_kind_valid"), "alerts")
    op.create_check_constraint(op.f("ck_alerts_link_kind_valid"), "alerts", _OLD_LINKS)
    op.alter_column("alerts", "link_kind", type_=sa.String(16))

    op.drop_table("broker_authorizations")

    # The old model has two fixed providers and one connection each.
    op.drop_index("uq_broker_events_expire", table_name="broker_events")
    op.execute("DELETE FROM broker_events WHERE action = 'expire'")
    op.execute("DELETE FROM broker_events WHERE provider NOT IN ('zerodha', 'fyers')")
    op.drop_constraint(op.f("ck_broker_events_action_valid"), "broker_events")
    op.create_check_constraint(op.f("ck_broker_events_action_valid"), "broker_events", _OLD_ACTIONS)
    op.drop_constraint(op.f("ck_broker_events_provider_format"), "broker_events")
    op.create_check_constraint(
        op.f("ck_broker_events_provider_valid"), "broker_events", _OLD_PROVIDERS
    )
    op.alter_column("broker_events", "provider", type_=sa.String(16))
    op.drop_column("broker_events", "connection_id")

    op.execute("DELETE FROM broker_connections WHERE provider NOT IN ('zerodha', 'fyers')")
    op.execute(
        "DELETE FROM broker_connections c USING broker_connections o"
        " WHERE c.user_id = o.user_id AND c.provider = o.provider"
        " AND (c.connected_at, c.id) > (o.connected_at, o.id)"
    )
    op.drop_constraint(op.f("uq_broker_connections_account"), "broker_connections")
    op.create_unique_constraint(
        op.f("uq_broker_connections_user_id_provider"),
        "broker_connections",
        ["user_id", "provider"],
    )
    op.drop_constraint(op.f("ck_broker_connections_status_reason_valid"), "broker_connections")
    op.drop_constraint(op.f("ck_broker_connections_provider_format"), "broker_connections")
    op.create_check_constraint(
        op.f("ck_broker_connections_provider_valid"), "broker_connections", _OLD_PROVIDERS
    )
    op.alter_column("broker_connections", "provider", type_=sa.String(16))
    op.drop_column("broker_connections", "portfolio")
    op.drop_column("broker_connections", "status_reason")
    op.drop_column("broker_connections", "account_ref")
