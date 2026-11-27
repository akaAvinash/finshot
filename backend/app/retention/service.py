"""Data retention: the user's period, and the purge job that enforces it.

The purge deletes, per user, the records in `PURGED` that were created before
`now - period`. It is idempotent and safe to run in several processes at once
(each user's purge holds a per-user advisory lock). For every user it moves
`purged_through` forward to the cutoff (never back, so lengthening the period
cannot bring a purged record back as "not yet reported"). A purge that deleted
anything is recorded in the audit log as `retention.purged` with counts only.

Run it by hand with `python -m app.retention.service`; the app also runs it
every `retention_purge_interval_seconds` when the worker is enabled."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import DateTime, cast, delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.models import AgentEvent
from app.alerts.models import Alert, AlertDelivery
from app.auth.models import AuditEvent, User
from app.core.config import Settings
from app.core.errors import ApiError
from app.retention.models import DataRetention
from app.retention.schemas import (
    CATEGORIES,
    DataRetentionBoundsOut,
    DataRetentionDeletedOut,
    DataRetentionOut,
    DataRetentionPurgeOut,
)

logger = structlog.get_logger(__name__)

Counts = dict[str, int]


def out_of_bounds(min_days: int, max_days: int) -> ApiError:
    return ApiError(
        400,
        "DATA_RETENTION_OUT_OF_BOUNDS",
        f"Choose a retention period between {min_days} and {max_days} days.",
    )


async def _delete_older(db: AsyncSession, user_id: uuid.UUID, cutoff: datetime) -> Counts:
    """Delete the user's purgeable records created before `cutoff`."""
    alerts = await db.execute(
        delete(Alert).where(Alert.user_id == user_id, Alert.created_at < cutoff)
    )
    deliveries = await db.execute(
        delete(AlertDelivery).where(
            AlertDelivery.user_id == user_id, AlertDelivery.created_at < cutoff
        )
    )
    events = await db.execute(
        delete(AgentEvent).where(AgentEvent.user_id == user_id, AgentEvent.created_at < cutoff)
    )
    return {
        "alerts": int(alerts.rowcount or 0),  # type: ignore[attr-defined]
        "alertDeliveries": int(deliveries.rowcount or 0),  # type: ignore[attr-defined]
        "agentEvents": int(events.rowcount or 0),  # type: ignore[attr-defined]
    }


class RetentionService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime],
    ) -> None:
        self._s = settings
        self._factory = session_factory
        self._clock = clock

    # ------------------------------------------------------------ settings

    def _out(self, row: DataRetention | None) -> DataRetentionOut:
        s = self._s
        counts = row.last_purge_counts if row is not None else None
        last = (
            DataRetentionPurgeOut(
                at=row.last_purge_at,
                deleted=DataRetentionDeletedOut(
                    alerts=int(counts.get("alerts", 0)),
                    alert_deliveries=int(counts.get("alertDeliveries", 0)),
                    agent_events=int(counts.get("agentEvents", 0)),
                ),
            )
            if row is not None and row.last_purge_at is not None and counts is not None
            else None
        )
        days = row.retention_days if row is not None else None
        return DataRetentionOut(
            retention_days=days if days is not None else s.data_retention_default_days,
            default_days=s.data_retention_default_days,
            bounds=DataRetentionBoundsOut(
                min_days=s.data_retention_min_days, max_days=s.data_retention_max_days
            ),
            categories=list(CATEGORIES),
            last_purge=last,
            updated_at=row.updated_at if row is not None else None,
        )

    async def get(self, user_id: uuid.UUID) -> DataRetentionOut:
        async with self._factory() as db, db.begin():
            row = await db.get(DataRetention, user_id)
            return self._out(row)

    async def update(self, user_id: uuid.UUID, days: int) -> DataRetentionOut:
        s = self._s
        if not s.data_retention_min_days <= days <= s.data_retention_max_days:
            raise out_of_bounds(s.data_retention_min_days, s.data_retention_max_days)
        async with self._factory() as db, db.begin():
            await db.execute(select(func.pg_advisory_xact_lock(_lock_key(user_id))))
            now = self._clock()
            row = await db.get(DataRetention, user_id, populate_existing=True)
            before = (
                row.retention_days
                if row is not None and row.retention_days is not None
                else s.data_retention_default_days
            )
            if row is None:
                row = DataRetention(user_id=user_id)
                db.add(row)
            if row.retention_days != days:
                row.retention_days = days
                row.updated_at = now
                if before != days:
                    db.add(
                        AuditEvent(
                            user_id=user_id,
                            actor=f"user:{user_id}",
                            action="settings.data_retention_updated",
                            resource=f"data_retention:{user_id}",
                            metadata_redacted={"before": before, "after": days},
                            created_at=now,
                        )
                    )
            await db.flush()
            return self._out(row)

    # --------------------------------------------------------------- purge

    async def purge_user(self, user_id: uuid.UUID) -> Counts:
        async with self._factory() as db, db.begin():
            await db.execute(select(func.pg_advisory_xact_lock(_lock_key(user_id))))
            now = self._clock()
            row = await db.get(DataRetention, user_id, populate_existing=True)
            days = (
                row.retention_days
                if row is not None and row.retention_days is not None
                else self._s.data_retention_default_days
            )
            cutoff = now - timedelta(days=days)
            counts = await _delete_older(db, user_id, cutoff)
            values: dict[str, Any] = {"user_id": user_id, "purged_through": cutoff}
            update_set: dict[str, Any] = {
                "purged_through": func.greatest(
                    func.coalesce(DataRetention.purged_through, cutoff), cutoff
                )
            }
            if any(counts.values()):
                values |= {"last_purge_at": now, "last_purge_counts": counts}
                update_set |= {"last_purge_at": now, "last_purge_counts": counts}
                db.add(
                    AuditEvent(
                        user_id=user_id,
                        actor="system:retention",
                        action="retention.purged",
                        resource=f"data_retention:{user_id}",
                        metadata_redacted={"retentionDays": days, "deleted": counts},
                        created_at=now,
                    )
                )
            await db.execute(
                insert(DataRetention)
                .values(**values)
                .on_conflict_do_update(index_elements=[DataRetention.user_id], set_=update_set)
            )
        return counts

    async def purge_all(self) -> Counts:
        """Purge every user. Returns the totals deleted."""
        async with self._factory() as db:
            user_ids = list((await db.scalars(select(User.id).order_by(User.id))).all())
        totals: Counts = dict.fromkeys(CATEGORIES, 0)
        failed = 0
        for user_id in user_ids:
            # One user's failure (for example a statement timeout) must not starve the
            # users after it: every pass would otherwise stop at the same place.
            try:
                counts = await self.purge_user(user_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failed += 1
                logger.warning(
                    "retention_user_failed", user_id=str(user_id), error_type=type(exc).__name__
                )
                continue
            for key, value in counts.items():
                totals[key] += value
        if any(totals.values()):
            logger.info("retention_purged", **totals)
        if failed:
            logger.warning("retention_pass_incomplete", failed_users=failed)
        return totals

    async def run_worker(self, interval_seconds: float) -> None:
        while True:
            started = _monotonic()
            try:
                await self.purge_all()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("retention_worker_error", error_type=type(exc).__name__)
            # Passes start one interval apart, however long a pass took.
            await asyncio.sleep(max(0.0, interval_seconds - (_monotonic() - started)))


_monotonic = time.monotonic


def _lock_key(user_id: uuid.UUID) -> Any:
    return func.hashtextextended(f"retention:{user_id}", 0)


def purged_floor(user_id_column: Any) -> Any:
    """SQL for the user's purge watermark, or -infinity when never purged.
    Producers compare their source timestamps with it."""
    return func.coalesce(
        select(DataRetention.purged_through)
        .where(DataRetention.user_id == user_id_column)
        .scalar_subquery(),
        cast(literal("-infinity"), DateTime(timezone=True)),
    )


async def _main() -> None:
    from app.core.config import get_settings
    from app.db.session import create_engine, create_session_factory

    settings = get_settings()
    engine = create_engine(settings)
    try:
        from datetime import UTC

        service = RetentionService(
            settings=settings,
            session_factory=create_session_factory(engine),
            clock=lambda: datetime.now(UTC),
        )
        print(await service.purge_all())
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
