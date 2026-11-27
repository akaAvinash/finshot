"""Alert tables (migration 0009).

`alerts` holds one row per alert. Each row has a dedupe key derived from the
source occurrence it describes, unique per user, so a producer that runs
twice (a retry, two workers) records it once. Rows never change except
`acknowledged_at`, which goes from null to a time once (the
alerts_acknowledge_only() trigger rejects any other UPDATE). DELETE stays
possible so deleting a user can cascade.

`alert_preferences` holds one row per user who saved preferences; a user
without a row has the defaults (every severity on)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_alerts_dedupe"),
        CheckConstraint("severity IN ('critical', 'warning', 'info')", name="severity_valid"),
        CheckConstraint(
            "source IN ('paper', 'brokers', 'agents', 'security')", name="source_valid"
        ),
        CheckConstraint(
            "environment IS NULL OR environment IN ('PAPER', 'DEMO')", name="environment_valid"
        ),
        CheckConstraint(
            "link_kind IS NULL OR link_kind IN"
            " ('paper-trade', 'paper-order', 'paper-replay', 'broker', 'broker-connection',"
            " 'session')",
            name="link_kind_valid",
        ),
        CheckConstraint("(link_kind IS NULL) = (link_id IS NULL)", name="link_complete"),
        Index("ix_alerts_user_id_seq", "user_id", "seq"),
        Index("ix_alerts_user_id_created_at", "user_id", "created_at"),
        Index(
            "ix_alerts_user_id_unread",
            "user_id",
            "severity",
            postgresql_where=text("acknowledged_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    dedupe_key: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(16))
    severity: Mapped[str] = mapped_column(String(8))
    environment: Mapped[str | None] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    link_kind: Mapped[str | None] = mapped_column(String(24))
    link_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertPreference(Base):
    __tablename__ = "alert_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    warning: Mapped[bool] = mapped_column(Boolean)
    info: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
