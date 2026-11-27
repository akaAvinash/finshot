"""Channel settings, delivery records and the delivery worker.

Worker pass (idempotent, safe in several processes):
1. **Enqueue.** One INSERT ... SELECT creates a `pending` delivery for every
   recent alert (within `notify_lookback_seconds`) on every channel the user
   has enabled, recorded at or after the channel was enabled, whose severity
   is at or above the channel's minimum. A partial unique index on
   (alert_id, channel) with ON CONFLICT DO NOTHING keeps it to one row each.
2. **Claim.** Pending rows due now are locked FOR UPDATE SKIP LOCKED; each
   claim counts an attempt and moves `next_attempt_at` forward (a lease and
   the retry backoff) in the same commit, so no other worker sends it.
3. **Send** outside the transaction, then record `sent`, or `failed` after
   the third attempt. A crash between send and record retries the row later,
   so delivery is at least once.

Rows the claim can decide without sending become `skipped`: the channel was
turned off (alerts only), has no provider or no destination, or the user's
per-channel daily cap is reached."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, case, delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerts.catalog import Severity
from app.alerts.delivery import (
    CHANNELS,
    Channel,
    Notification,
    NotificationDeliveryError,
    NotificationProvider,
)
from app.alerts.models import Alert, AlertChannelSetting, AlertDelivery, EmailSendAttempt
from app.alerts.schemas import (
    AlertChannelOut,
    AlertChannelsIn,
    AlertDeliveryListOut,
    AlertDeliveryOut,
)
from app.auth.models import AuditEvent, Invite, User
from app.auth.otp import mask_destination
from app.core.config import Settings
from app.core.errors import ApiError

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS = 3
_BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15))
_BATCH = 50
_Claim = tuple[uuid.UUID, Notification, NotificationProvider, int, datetime]
_RANK = {"info": 1, "warning": 2, "critical": 3}
TEST_TITLE = "Tradeo test message"
TEST_BODY = "This is a test message from Tradeo. Alerts can reach you on this channel."


def channel_unavailable() -> ApiError:
    return ApiError(409, "ALERT_CHANNEL_UNAVAILABLE", "This delivery channel is not available yet.")


def _rank(column: Any) -> Any:
    return case((column == "critical", 3), (column == "warning", 2), else_=1)


class AlertDeliveryService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime],
        providers: dict[Channel, NotificationProvider],
    ) -> None:
        self._s = settings
        self._factory = session_factory
        self._clock = clock
        self._providers = providers

    # ---------------------------------------------------------- destinations

    async def _destinations(
        self, db: AsyncSession, user_id: uuid.UUID
    ) -> dict[Channel, str | None]:
        row = (
            await db.execute(
                select(User.phone_e164, Invite.email)
                .outerjoin(
                    Invite,
                    (Invite.phone_e164 == User.phone_e164) & Invite.revoked_at.is_(None),
                )
                .where(User.id == user_id)
            )
        ).first()
        phone, email = (row[0], row[1]) if row is not None else (None, None)
        return {"email": email, "sms": phone, "push": None}

    def _availability(self, channel: Channel, destination: str | None) -> str | None:
        if not self._providers[channel].configured:
            return "PROVIDER_NOT_CONFIGURED"
        if destination is None:
            return "NO_DESTINATION"
        return None

    async def channels_out(self, db: AsyncSession, user_id: uuid.UUID) -> list[AlertChannelOut]:
        destinations = await self._destinations(db, user_id)
        settings = {
            row.channel: row
            for row in await db.scalars(
                select(AlertChannelSetting).where(AlertChannelSetting.user_id == user_id)
            )
        }
        out: list[AlertChannelOut] = []
        for channel in CHANNELS:
            row = settings.get(channel)
            destination = destinations[channel]
            reason = self._availability(channel, destination)
            out.append(
                AlertChannelOut(
                    channel=channel,
                    available=reason is None,
                    unavailable_reason=reason,
                    enabled=bool(row.enabled) if row is not None else False,
                    min_severity=row.min_severity if row is not None else "critical",
                    destination_masked=(
                        mask_destination(destination) if destination is not None else None
                    ),
                )
            )
        return out

    # -------------------------------------------------------------- settings

    async def save_channels(self, user_id: uuid.UUID, body: AlertChannelsIn) -> None:
        wanted = {c.channel: c for c in body.channels}
        if len(wanted) != len(CHANNELS):
            raise ApiError(400, "INVALID_REQUEST", "The request parameters are invalid.")
        async with self._factory() as db, db.begin():
            await db.execute(
                select(func.pg_advisory_xact_lock(func.hashtextextended(f"alerts:{user_id}", 0)))
            )
            now = self._clock()
            destinations = await self._destinations(db, user_id)
            current = {
                row.channel: row
                for row in await db.scalars(
                    select(AlertChannelSetting).where(AlertChannelSetting.user_id == user_id)
                )
            }
            before: dict[str, Any] = {}
            after: dict[str, Any] = {}
            for channel in CHANNELS:
                new = wanted[channel]
                row = current.get(channel)
                old_enabled = bool(row.enabled) if row is not None else False
                old_min = row.min_severity if row is not None else "critical"
                # Only turning an unavailable channel on is refused. One that was
                # on and became unavailable may stay on; it sends nothing.
                if (
                    new.enabled
                    and not old_enabled
                    and self._availability(channel, destinations[channel])
                ):
                    raise channel_unavailable()
                if (old_enabled, old_min) == (new.enabled, new.min_severity):
                    continue
                before[channel] = {"enabled": old_enabled, "minSeverity": old_min}
                after[channel] = {"enabled": new.enabled, "minSeverity": new.min_severity}
                if row is None:
                    row = AlertChannelSetting(user_id=user_id, channel=channel)
                    db.add(row)
                if new.enabled and not old_enabled:
                    row.enabled_at = now
                row.enabled = new.enabled
                row.min_severity = new.min_severity
                row.updated_at = now
            if after:
                db.add(
                    AuditEvent(
                        user_id=user_id,
                        actor=f"user:{user_id}",
                        action="alerts.channels",
                        resource=f"alerts:{user_id}",
                        metadata_redacted={"before": before, "after": after},
                        created_at=now,
                    )
                )

    # ---------------------------------------------------------------- tests

    async def queue_test(self, user_id: uuid.UUID, channel: Channel) -> AlertDeliveryOut:
        async with self._factory() as db, db.begin():
            await db.execute(
                select(func.pg_advisory_xact_lock(func.hashtextextended(f"alerts:{user_id}", 0)))
            )
            now = self._clock()
            destinations = await self._destinations(db, user_id)
            if self._availability(channel, destinations[channel]):
                raise channel_unavailable()
            window = now - timedelta(hours=1)
            recent = list(
                (
                    await db.scalars(
                        select(AlertDelivery.created_at)
                        .where(
                            AlertDelivery.user_id == user_id,
                            AlertDelivery.kind == "test",
                            AlertDelivery.created_at > window,
                        )
                        .order_by(AlertDelivery.created_at)
                    )
                ).all()
            )
            if len(recent) >= self._s.notify_test_per_hour:
                retry = max(1, int((recent[0] + timedelta(hours=1) - now).total_seconds()) + 1)
                raise ApiError(
                    429,
                    "RATE_LIMITED",
                    "Too many attempts. Try again later.",
                    retry_after_seconds=retry,
                )
            row = AlertDelivery(
                id=uuid.uuid4(),
                user_id=user_id,
                alert_id=None,
                kind="test",
                channel=channel,
                status="pending",
                attempts=0,
                simulated=False,
                next_attempt_at=now,
                created_at=now,
            )
            db.add(row)
            await db.flush()
            return _delivery_out(row)

    async def recent(self, user_id: uuid.UUID) -> AlertDeliveryListOut:
        async with self._factory() as db, db.begin():
            rows = (
                await db.scalars(
                    select(AlertDelivery)
                    .where(AlertDelivery.user_id == user_id)
                    .order_by(AlertDelivery.created_at.desc(), AlertDelivery.id.desc())
                    .limit(50)
                )
            ).all()
            return AlertDeliveryListOut(items=[_delivery_out(r) for r in rows])

    # ---------------------------------------------------------------- worker

    async def enqueue(self) -> int:
        async with self._factory() as db, db.begin():
            now = self._clock()
            since = now - timedelta(seconds=self._s.notify_lookback_seconds)
            source = (
                select(
                    Alert.user_id,
                    Alert.id,
                    literal("alert"),
                    AlertChannelSetting.channel,
                    literal("pending"),
                    literal(0),
                    literal(False),
                    literal(now),
                    literal(now),
                )
                .join(
                    AlertChannelSetting,
                    and_(
                        AlertChannelSetting.user_id == Alert.user_id,
                        AlertChannelSetting.enabled.is_(True),
                        Alert.created_at >= AlertChannelSetting.enabled_at,
                        _rank(Alert.severity) >= _rank(AlertChannelSetting.min_severity),
                    ),
                )
                .where(Alert.created_at > since)
            )
            result = await db.execute(
                insert(AlertDelivery)
                .from_select(
                    [
                        "user_id",
                        "alert_id",
                        "kind",
                        "channel",
                        "status",
                        "attempts",
                        "simulated",
                        "next_attempt_at",
                        "created_at",
                    ],
                    source,
                    include_defaults=False,
                )
                .on_conflict_do_nothing(
                    index_elements=["alert_id", "channel"],
                    index_where=AlertDelivery.alert_id.is_not(None),
                )
            )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def _claim(self) -> list[_Claim]:
        claimed: list[_Claim] = []
        async with self._factory() as db, db.begin():
            now = self._clock()
            rows = (
                await db.scalars(
                    select(AlertDelivery)
                    .where(AlertDelivery.status == "pending", AlertDelivery.next_attempt_at <= now)
                    .order_by(AlertDelivery.next_attempt_at)
                    .limit(_BATCH)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            await db.execute(
                delete(EmailSendAttempt).where(EmailSendAttempt.at < day - timedelta(days=2))
            )
            # The daily check and the attempt increment below must not interleave
            # with another claimer for the same user and channel. Locks are taken
            # in sorted key order so concurrent batches cannot deadlock.
            if any(r.channel == "email" for r in rows) and not self._providers["email"].simulated:
                # One mailbox, one cap: serialize real-email claims across workers.
                await db.execute(
                    select(func.pg_advisory_xact_lock(func.hashtextextended("alerts:email-cap", 0)))
                )
            for user_id, chan in sorted({(r.user_id, r.channel) for r in rows}, key=str):
                await db.execute(
                    select(
                        func.pg_advisory_xact_lock(
                            func.hashtextextended(f"alerts:{user_id}:{chan}", 0)
                        )
                    )
                )
            for row in rows:
                if row.attempts >= MAX_ATTEMPTS:  # an interrupted last attempt
                    row.status = "failed"
                    continue
                channel: Channel = row.channel  # type: ignore[assignment]
                provider = self._providers[channel]
                destination = (await self._destinations(db, row.user_id))[channel]
                reason = self._availability(channel, destination)
                if reason is None and row.kind == "alert":
                    setting = await db.get(AlertChannelSetting, (row.user_id, channel))
                    if setting is None or not setting.enabled:
                        reason = "CHANNEL_DISABLED"
                if reason is None:
                    used = await db.scalar(
                        select(func.count())
                        .select_from(AlertDelivery)
                        .where(
                            AlertDelivery.user_id == row.user_id,
                            AlertDelivery.channel == channel,
                            AlertDelivery.last_attempt_at >= day,
                        )
                    )
                    if (used or 0) >= self._s.notify_daily_limit_per_channel:
                        reason = "DAILY_LIMIT"
                if reason is None and channel == "email" and not provider.simulated:
                    reason = await self._email_cap_reason(db, row, now, day)
                if reason is not None:
                    row.status = "skipped"
                    row.status_reason = reason
                    continue
                assert destination is not None  # noqa: S101 - checked by _availability
                title, body = TEST_TITLE, TEST_BODY
                if row.kind == "alert":
                    alert = await db.get(Alert, row.alert_id) if row.alert_id else None
                    if alert is None:  # purged meanwhile
                        row.status, row.status_reason = "skipped", "CHANNEL_DISABLED"
                        continue
                    title, body = alert.title, alert.message
                row.attempts += 1
                row.last_attempt_at = now
                if channel == "email" and not provider.simulated:
                    db.add(EmailSendAttempt(user_id=row.user_id, at=now))
                row.next_attempt_at = now + _BACKOFF[min(row.attempts, MAX_ATTEMPTS) - 1]
                row.destination_masked = mask_destination(destination)
                row.simulated = provider.simulated
                row.status_reason = None
                claimed.append(
                    (
                        row.id,
                        Notification(
                            delivery_id=str(row.id),
                            channel=channel,
                            destination=destination,
                            title=title,
                            body=body,
                            link=f"{self._s.public_origin.rstrip('/')}/alerts",
                        ),
                        provider,
                        row.attempts,
                        row.next_attempt_at,
                    )
                )
        return claimed

    async def _email_cap_reason(
        self, db: AsyncSession, row: AlertDelivery, now: datetime, day: datetime
    ) -> str | None:
        """Hard caps for real email, counted per send attempt (retries included)
        by each attempt's own timestamp: the whole mailbox per UTC day, then this
        user per rolling hour. The caller holds the mailbox advisory lock."""
        today = await db.scalar(
            select(func.count()).select_from(EmailSendAttempt).where(EmailSendAttempt.at >= day)
        )
        if int(today or 0) >= self._s.notify_email_daily_cap:
            return "DAILY_LIMIT"
        recent = await db.scalar(
            select(func.count())
            .select_from(EmailSendAttempt)
            .where(
                EmailSendAttempt.user_id == row.user_id,
                EmailSendAttempt.at >= now - timedelta(hours=1),
            )
        )
        if int(recent or 0) >= self._s.notify_email_per_user_per_hour:
            return "DAILY_LIMIT"
        return None

    async def _still_owned(self, delivery_id: uuid.UUID, attempts: int, lease: datetime) -> bool:
        """Atomically re-take the lease just before sending. False when another
        worker has claimed the row since (different attempts or lease)."""
        now = self._clock()
        async with self._factory() as db, db.begin():
            result = await db.execute(
                update(AlertDelivery)
                .where(
                    AlertDelivery.id == delivery_id,
                    AlertDelivery.status == "pending",
                    AlertDelivery.attempts == attempts,
                    AlertDelivery.next_attempt_at == lease,
                )
                .values(next_attempt_at=now + _BACKOFF[min(attempts, MAX_ATTEMPTS) - 1])
            )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def send_due(self) -> int:
        """Send every due delivery once. Returns how many were sent."""
        sent = 0
        for delivery_id, notification, provider, attempts, lease in await self._claim():
            if not await self._still_owned(delivery_id, attempts, lease):
                continue  # the lease ran out and another worker took it
            try:
                await provider.send(notification)
            except NotificationDeliveryError as exc:
                logger.warning("notification_failed", channel=notification.channel, reason=str(exc))
                async with self._factory() as db, db.begin():
                    await db.execute(
                        update(AlertDelivery)
                        .where(AlertDelivery.id == delivery_id, AlertDelivery.status == "pending")
                        .values(
                            status_reason="PROVIDER_ERROR",
                            status=case(
                                (AlertDelivery.attempts >= MAX_ATTEMPTS, "failed"),
                                else_="pending",
                            ),
                        )
                    )
                continue
            async with self._factory() as db, db.begin():
                await db.execute(
                    update(AlertDelivery)
                    .where(AlertDelivery.id == delivery_id, AlertDelivery.status == "pending")
                    .values(status="sent", status_reason=None, sent_at=self._clock())
                )
            sent += 1
        return sent

    async def run_once(self) -> int:
        await self.enqueue()
        return await self.send_due()

    async def run_worker(self, poll_seconds: float) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("notify_worker_error", error_type=type(exc).__name__)
            await asyncio.sleep(poll_seconds)


def _delivery_out(row: AlertDelivery) -> AlertDeliveryOut:
    return AlertDeliveryOut(
        id=str(row.id),
        kind=row.kind,
        alert_id=str(row.alert_id) if row.alert_id is not None else None,
        channel=row.channel,
        status=row.status,
        status_reason=row.status_reason,
        attempts=row.attempts,
        simulated=row.simulated,
        destination_masked=row.destination_masked,
        created_at=row.created_at,
        sent_at=row.sent_at,
    )


def severity_at_least(severity: Severity, minimum: Severity) -> bool:
    return _RANK[severity] >= _RANK[minimum]
