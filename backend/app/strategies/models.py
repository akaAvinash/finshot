"""Phase C1 tables: strategies, strategy_versions. Both carry user_id.

strategy_versions rows are immutable: a database trigger rejects UPDATE
(migration 0004). Rows are only removed by cascade when a user is deleted."""

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
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_UUID_DEFAULT = text("gen_random_uuid()")


class Strategy(Base):
    __tablename__ = "strategies"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'paused')", name="status_valid"),
        CheckConstraint(
            "draft_backtest IS NULL OR draft_backtest IN ('passed', 'failed', 'unavailable')",
            name="draft_backtest_valid",
        ),
        CheckConstraint(
            "draft_risk_review IS NULL OR draft_risk_review IN ('approved', 'rejected', 'pending')",
            name="draft_risk_review_valid",
        ),
        CheckConstraint(
            "(draft_parameters IS NULL) = (draft_backtest IS NULL)"
            " AND (draft_parameters IS NULL) = (draft_risk_review IS NULL)",
            name="draft_complete",
        ),
        Index("ix_strategies_user_id_seq", "user_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16))
    # none_as_null: Python None must be SQL NULL, not JSON null, for draft_complete.
    draft_parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    draft_backtest: Mapped[str | None] = mapped_column(String(16))
    draft_risk_review: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("strategy_id", "number", name="uq_strategy_versions_strategy_id_number"),
        CheckConstraint("number >= 1", name="number_positive"),
        CheckConstraint("parameters_hash ~ '^[0-9a-f]{64}$'", name="hash_format"),
        Index("ix_strategy_versions_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=_UUID_DEFAULT
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # SHA-256 of the canonical JSON of `parameters`, for integrity checks.
    parameters_hash: Mapped[str] = mapped_column(String(64))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
