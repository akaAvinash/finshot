"""Phase B2 tables: broker_connections, broker_events. Both carry user_id and
every query filters on it."""

from __future__ import annotations

import uuid
from datetime import datetime

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
_PROVIDER_CHECK = "provider IN ('zerodha', 'fyers')"


class BrokerConnection(Base):
    """A current demo connection. Deleted on disconnect; history stays in
    broker_events. Holds no tokens or credentials."""

    __tablename__ = "broker_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_broker_connections_user_id_provider"),
        CheckConstraint(_PROVIDER_CHECK, name="provider_valid"),
        CheckConstraint("environment = 'DEMO'", name="environment_demo"),
        CheckConstraint("expires_at > connected_at", name="expiry_after_connect"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16))
    environment: Mapped[str] = mapped_column(String(8), server_default="DEMO")
    masked_account_id: Mapped[str] = mapped_column(String(32))
    scopes: Mapped[list[str]] = mapped_column(JSONB)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrokerEvent(Base):
    """Append-only log of the user's demo broker actions."""

    __tablename__ = "broker_events"
    __table_args__ = (
        CheckConstraint(_PROVIDER_CHECK, name="provider_valid"),
        CheckConstraint(
            "action IN ('connect', 'reconnect', 'sync', 'disconnect')", name="action_valid"
        ),
        Index("ix_broker_events_user_id_seq", "user_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    # Insertion order. Timestamps can tie; seq never does.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
