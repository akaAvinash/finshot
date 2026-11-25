"""Agent tables: agent_events and agent_runs (migration 0008).

`agent_events` is append-only (the paper_ledger_append_only() trigger rejects
UPDATE). Each event has a dedupe key derived from the paper data it is about,
so evaluating the same data twice, even from two workers, records it once.
`agent_runs` holds one row per user: when the agents last evaluated the
user's paper data, the paper account change they saw, and what they
remember between passes. `agent_worker` holds when a worker last ended a
pass. Rows go only by cascade when a user is deleted."""

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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint("user_id", "agent_id", "dedupe_key", name="uq_agent_events_dedupe"),
        CheckConstraint(
            "agent_id IN ('market-scanner', 'strategy-analyst', 'risk-explainer',"
            " 'execution-monitor')",
            name="agent_id_valid",
        ),
        CheckConstraint("severity IN ('info', 'warning')", name="severity_valid"),
        CheckConstraint(
            "link_kind IS NULL OR link_kind IN ('paper-trade', 'paper-order', 'paper-replay')",
            name="link_kind_valid",
        ),
        CheckConstraint("(link_kind IS NULL) = (link_id IS NULL)", name="link_complete"),
        Index("ix_agent_events_user_id_seq", "user_id", "seq"),
        Index("ix_agent_events_user_id_agent_id_seq", "user_id", "agent_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    agent_id: Mapped[str] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(128))
    reason_code: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)
    link_kind: Mapped[str | None] = mapped_column(String(16))
    link_id: Mapped[str | None] = mapped_column(String(64))
    data_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentRun(Base):
    __tablename__ = "agent_runs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[dict[str, Any]] = mapped_column(JSONB)


class AgentWorker(Base):
    """One row: when an agent worker last ended a pass (evaluated every
    pending user). Health reports `stale` when it is too old."""

    __tablename__ = "agent_worker"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    pass_ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
