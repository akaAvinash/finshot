"""Per-user demo broker connections: snapshot and the four actions.

Each action runs in one transaction under a per-(user, provider) advisory
lock, so concurrent clicks cannot double-connect or interleave a sync with a
disconnect. Every successful action appends a broker event and an audit event
in the same transaction."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Literal

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuditEvent
from app.brokers.adapter import PROVIDERS, BrokerAdapter, BrokerId, BrokerUnavailableError
from app.brokers.models import BrokerConnection, BrokerEvent
from app.brokers.schemas import (
    MAX_EVENTS,
    BrokerAccountOut,
    BrokerAction,
    BrokerConnectionOut,
    BrokerEventOut,
    BrokerSnapshotOut,
)
from app.core.errors import ApiError
from app.db.session import begin_consistent_read

logger = structlog.get_logger(__name__)

Status = Literal["connected", "expired", "disconnected"]

ALLOWED_ACTIONS: dict[Status, frozenset[BrokerAction]] = {
    "connected": frozenset({"sync", "disconnect"}),
    "expired": frozenset({"reconnect", "disconnect"}),
    "disconnected": frozenset({"connect"}),
}


def status_of(expires_at: datetime | None, now: datetime) -> Status:
    """A connection is expired at or after its expiry instant."""
    if expires_at is None:
        return "disconnected"
    return "connected" if now < expires_at else "expired"


def unavailable() -> ApiError:
    return ApiError(
        503, "BROKER_UNAVAILABLE", "Broker accounts are temporarily unavailable. Try again shortly."
    )


def conflict() -> ApiError:
    return ApiError(
        409, "BROKER_ACTION_CONFLICT", "This broker account is not ready for that action."
    )


class BrokerService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        adapter: BrokerAdapter | None,
        clock: Callable[[], datetime],
        timeout_seconds: float,
    ) -> None:
        """`adapter=None` means BROKER_PROVIDER=disabled: every call is 503."""
        self._factory = session_factory
        self._adapter = adapter
        self._clock = clock
        self._timeout = timeout_seconds
        # Test seams: between the two snapshot reads, and after an action
        # commits but before its result is read.
        self._between_snapshot_reads: Callable[[], None] | None = None
        self._before_result_snapshot: Callable[[], None] | None = None

    def _require_adapter(self) -> BrokerAdapter:
        if self._adapter is None:
            raise unavailable()
        return self._adapter

    async def snapshot(self, user_id: uuid.UUID) -> BrokerSnapshotOut:
        self._require_adapter()
        async with self._factory() as db:
            return await self._snapshot(db, user_id, self._clock())

    async def apply(
        self, user_id: uuid.UUID, provider: BrokerId, action: BrokerAction
    ) -> BrokerSnapshotOut:
        adapter = self._require_adapter()
        async with self._factory() as db:
            async with db.begin():
                await db.execute(
                    select(
                        func.pg_advisory_xact_lock(
                            func.hashtextextended(f"broker:{user_id}:{provider}", 0)
                        )
                    )
                )
                now = self._clock()
                conn = await db.scalar(
                    select(BrokerConnection).where(
                        BrokerConnection.user_id == user_id, BrokerConnection.provider == provider
                    )
                )
                status = status_of(conn.expires_at if conn else None, now)
                if action not in ALLOWED_ACTIONS[status]:
                    raise conflict()
                try:
                    async with asyncio.timeout(self._timeout):
                        await self._perform(db, adapter, user_id, provider, action, conn, now)
                except BrokerUnavailableError:
                    logger.warning("broker_unavailable", provider=provider, action=action)
                    raise unavailable() from None
                except TimeoutError:
                    logger.warning("broker_timeout", provider=provider, action=action)
                    raise unavailable() from None
                db.add(BrokerEvent(user_id=user_id, provider=provider, action=action, at=now))
                db.add(
                    AuditEvent(
                        user_id=user_id,
                        actor=f"user:{user_id}",
                        action=f"broker.{action}",
                        resource=f"broker:{provider}",
                        metadata_redacted={"environment": "DEMO"},
                        created_at=now,
                    )
                )
        # Read the result in a new session: the action's session still holds
        # the objects it wrote, which would hide anything committed since.
        if self._before_result_snapshot is not None:
            self._before_result_snapshot()
        async with self._factory() as fresh:
            return await self._snapshot(fresh, user_id, now)

    async def _perform(
        self,
        db: AsyncSession,
        adapter: BrokerAdapter,
        user_id: uuid.UUID,
        provider: BrokerId,
        action: BrokerAction,
        conn: BrokerConnection | None,
        now: datetime,
    ) -> None:
        if action in ("connect", "reconnect"):
            grant = await adapter.authorize(provider, now)
            if conn is None:
                conn = BrokerConnection(user_id=user_id, provider=provider)
                db.add(conn)
            conn.masked_account_id = grant.masked_account_id
            conn.scopes = list(grant.scopes)
            conn.connected_at = now
            conn.expires_at = grant.expires_at
            conn.last_synced_at = None
        elif action == "sync":
            if conn is None:  # unreachable: ALLOWED_ACTIONS requires a connection
                raise conflict()
            data = await adapter.fetch_account(provider, conn.masked_account_id)
            if data.masked_account_id != conn.masked_account_id:
                # The source answered for a different account: do not record a sync.
                raise BrokerUnavailableError("account mismatch")
            conn.last_synced_at = now
        else:  # disconnect
            await db.execute(
                delete(BrokerConnection).where(
                    BrokerConnection.user_id == user_id, BrokerConnection.provider == provider
                )
            )
        await db.flush()

    async def _snapshot(
        self, db: AsyncSession, user_id: uuid.UUID, now: datetime
    ) -> BrokerSnapshotOut:
        # Both reads see one committed state, so connections and events agree
        # even if another action commits in between.
        async with db.begin():
            await begin_consistent_read(db)
            rows = (
                await db.scalars(
                    select(BrokerConnection).where(BrokerConnection.user_id == user_id)
                )
            ).all()
            if self._between_snapshot_reads is not None:
                self._between_snapshot_reads()
            events = (
                await db.scalars(
                    select(BrokerEvent)
                    .where(BrokerEvent.user_id == user_id)
                    .order_by(BrokerEvent.seq.desc())
                    .limit(MAX_EVENTS)
                )
            ).all()
        by_provider = {row.provider: row for row in rows}
        return BrokerSnapshotOut(
            as_of=now,
            connections=[
                BrokerConnectionOut(provider=p, account=_account(by_provider.get(p)))
                for p in PROVIDERS
            ],
            events=[
                BrokerEventOut(id=str(e.id), provider=e.provider, action=e.action, at=e.at)
                for e in reversed(events)
            ],
        )


def _account(row: BrokerConnection | None) -> BrokerAccountOut | None:
    if row is None:
        return None
    return BrokerAccountOut(
        masked_account_id=row.masked_account_id,
        connected_at=row.connected_at,
        expires_at=row.expires_at,
        last_synced_at=row.last_synced_at,
        scopes=row.scopes,
    )
