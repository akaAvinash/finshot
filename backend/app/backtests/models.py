"""Phase C2 table: backtest_runs. Each row carries user_id.

`config` is the request as accepted (wire shape). `parameters` is a copy of
the strategy revision taken when the run was queued, so later draft edits do
not change the run. `result` is written once, by the worker."""

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
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')", name="status_valid"
        ),
        CheckConstraint(
            "(status = 'completed') = (result IS NOT NULL)", name="result_iff_completed"
        ),
        CheckConstraint("(status = 'failed') = (message IS NOT NULL)", name="message_iff_failed"),
        CheckConstraint("(status = 'queued') = (started_at IS NULL)", name="started_unless_queued"),
        Index("ix_backtest_runs_user_id_seq", "user_id", "seq"),
        Index(
            "ix_backtest_runs_active_seq",
            "seq",
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    strategy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    # none_as_null: Python None must be SQL NULL for the CHECKs above.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    message: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
