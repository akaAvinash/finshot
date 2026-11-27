"""Data retention table (migration 0017).

One row per user that saved a period or has been purged at least once.
`retention_days` null means the server default. `purged_through` is the
latest cutoff a purge applied for the user: everything the purge covers that
was created before it is gone. Producers that look for "not yet reported"
source records ignore sources older than it, so a purged alert or agent event
is never recorded again."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DataRetention(Base):
    __tablename__ = "data_retention"
    __table_args__ = (
        CheckConstraint(
            "retention_days IS NULL OR retention_days BETWEEN 1 AND 36500", name="days_range"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    retention_days: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_purge_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_purge_counts: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, server_default=text("NULL")
    )
