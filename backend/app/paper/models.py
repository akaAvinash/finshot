"""Paper tables: paper_accounts, paper_replays, paper_replay_finishes,
paper_orders, paper_trades, paper_events.

One paper account per user. `replay` numbers the account's replays: `assign`
starts a new one, and orders and trades belong to the replay that made them,
so the workspace shows only the current replay's. `paper_replays` records the
strategy version each replay used (migration 0007), so reports can attribute
fills. Replays, trades and events are append-only: a database trigger rejects
UPDATE (migrations 0006 and 0007). Rows are only removed by cascade when a
user is deleted."""

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
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID_DEFAULT = text("gen_random_uuid()")


class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    __table_args__ = (
        CheckConstraint("engine IN ('idle', 'running', 'halted')", name="engine_valid"),
        CheckConstraint("cash_paise >= 0", name="cash_nonnegative"),
        CheckConstraint("position_quantity >= 0", name="position_nonnegative"),
        CheckConstraint(
            "(position_quantity = 0) = (position_entry_paise IS NULL)"
            " AND (position_quantity = 0) = (position_stop_paise IS NULL)",
            name="position_complete",
        ),
        CheckConstraint(
            "(strategy_id IS NULL) = (version_number IS NULL)"
            " AND (strategy_id IS NULL) = (version_parameters IS NULL)"
            " AND (strategy_id IS NULL) = (instrument_id IS NULL)",
            name="assignment_complete",
        ),
        CheckConstraint(
            "sessions_done >= 0 AND sessions_done <= sessions_total", name="sessions_valid"
        ),
        CheckConstraint("session_fills >= 0", name="session_fills_nonnegative"),
        # Only a running engine is ticked; it needs an unfinished replay.
        CheckConstraint("engine <> 'running' OR NOT finished", name="running_unfinished"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    engine: Mapped[str] = mapped_column(String(16))
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE")
    )
    # The version pinned at assignment, copied so a later version does not
    # change a running replay.
    version_number: Mapped[int | None] = mapped_column(Integer)
    version_parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    instrument_id: Mapped[str | None] = mapped_column(String(64))
    replay: Mapped[int] = mapped_column(Integer)
    capital_paise: Mapped[int] = mapped_column(BigInteger)
    cash_paise: Mapped[int] = mapped_column(BigInteger)
    position_quantity: Mapped[int] = mapped_column(BigInteger)
    position_entry_paise: Mapped[int | None] = mapped_column(BigInteger)
    position_stop_paise: Mapped[int | None] = mapped_column(BigInteger)
    # Entry fee of the open position, charged against its exit P&L.
    position_fees_paise: Mapped[int] = mapped_column(BigInteger)
    sessions_done: Mapped[int] = mapped_column(Integer)
    sessions_total: Mapped[int] = mapped_column(Integer)
    finished: Mapped[bool]
    # Signed realised P&L and fills of the last replayed session.
    session_pnl_paise: Mapped[int] = mapped_column(BigInteger)
    session_fills: Mapped[int] = mapped_column(Integer)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperReplay(Base):
    __tablename__ = "paper_replays"
    __table_args__ = (
        CheckConstraint("replay >= 1", name="replay_positive"),
        CheckConstraint("version_number >= 1", name="version_positive"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    replay: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer)
    # The version's name, copied at assignment like its parameters.
    strategy_name: Mapped[str] = mapped_column(String(64))
    instrument_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperReplayFinish(Base):
    """When a replay finished (replayed its last session). Written by the paper
    engine in the tick that finishes it (migration 0008), append-only. Agents
    read it so a finished replay is summarised even if it is reassigned
    before they run."""

    __tablename__ = "paper_replay_finishes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    replay: Mapped[int] = mapped_column(Integer, primary_key=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    __table_args__ = (
        CheckConstraint("side IN ('Buy', 'Sell')", name="side_valid"),
        CheckConstraint("status IN ('queued', 'filled', 'cancelled')", name="status_valid"),
        CheckConstraint("quantity >= 1", name="quantity_positive"),
        CheckConstraint("limit_paise >= 0", name="limit_nonnegative"),
        Index("ix_paper_orders_user_id_seq", "user_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    replay: Mapped[int] = mapped_column(Integer)
    instrument: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(BigInteger)
    limit_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperTrade(Base):
    __tablename__ = "paper_trades"
    __table_args__ = (
        CheckConstraint("side IN ('Buy', 'Sell')", name="side_valid"),
        CheckConstraint(
            "reason IN ('entry', 'signal-exit', 'stop-loss', 'end-of-replay')",
            name="reason_valid",
        ),
        CheckConstraint("quantity >= 1", name="quantity_positive"),
        CheckConstraint("fill_paise >= 1", name="fill_positive"),
        CheckConstraint("fees_paise >= 0", name="fees_nonnegative"),
        Index("ix_paper_trades_user_id_seq", "user_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    replay: Mapped[int] = mapped_column(Integer)
    instrument: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(BigInteger)
    fill_paise: Mapped[int] = mapped_column(BigInteger)
    fees_paise: Mapped[int] = mapped_column(BigInteger)
    pnl_paise: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(16))
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperEvent(Base):
    __tablename__ = "paper_events"
    __table_args__ = (Index("ix_paper_events_user_id_seq", "user_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
