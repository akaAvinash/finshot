"""Phase B2 tables: broker_connections, broker_events. Both carry user_id and
every query filters on it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID_DEFAULT = text("gen_random_uuid()")
_PROVIDER_FORMAT = "provider ~ '^[a-z][a-z0-9_-]{1,31}$'"


class BrokerConnection(Base):
    """A current demo connection. Deleted on disconnect; history stays in
    broker_events. Holds no tokens or credentials. `account_ref` is the
    provider's own account reference (never shown); authorizing the same
    account again renews the same row. `portfolio` is what the last sync
    stored, in the canonical shapes."""

    __tablename__ = "broker_connections"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", "account_ref", name="uq_broker_connections_account"
        ),
        CheckConstraint(_PROVIDER_FORMAT, name="provider_format"),
        CheckConstraint(
            "status_reason IS NULL OR status_reason = 'AUTH_INVALIDATED'",
            name="status_reason_valid",
        ),
        CheckConstraint("environment = 'DEMO'", name="environment_demo"),
        CheckConstraint("expires_at > connected_at", name="expiry_after_connect"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))
    environment: Mapped[str] = mapped_column(String(8), server_default="DEMO")
    account_ref: Mapped[str] = mapped_column(String(64))
    masked_account_id: Mapped[str] = mapped_column(String(32))
    status_reason: Mapped[str | None] = mapped_column(String(16))
    portfolio: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrokerEvent(Base):
    """Append-only log of the user's demo broker actions."""

    __tablename__ = "broker_events"
    __table_args__ = (
        CheckConstraint(_PROVIDER_FORMAT, name="provider_format"),
        CheckConstraint(
            "action IN ('connect', 'reconnect', 'sync', 'disconnect', 'expire')",
            name="action_valid",
        ),
        Index("ix_broker_events_user_id_seq", "user_id", "seq"),
        Index(
            "uq_broker_events_expire",
            "connection_id",
            "at",
            unique=True,
            postgresql_where=text("action = 'expire'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    # Insertion order. Timestamps can tie; seq never does.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Kept after a disconnect, so history still names its connection.
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BrokerAuthorization(Base):
    """A pending two-step authorization. Only a hash of the single-use `state`
    is stored; it is bound to the session that started it."""

    __tablename__ = "broker_authorizations"
    __table_args__ = (
        CheckConstraint(_PROVIDER_FORMAT, name="provider_format"),
        CheckConstraint("expires_at > created_at", name="expiry_after_start"),
        UniqueConstraint("state_hash", name="uq_broker_authorizations_state_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(32))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    state_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
