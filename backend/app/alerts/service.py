"""Alerts: the inbox endpoints and the alert worker.

Most alerts are written by their producers in the transaction of the change
they describe (see app.alerts.producer). The worker records the two kinds
that have no such transaction: a demo broker connection passing its expiry,
and an execution-monitor reconciliation mismatch. Each pass is one
INSERT ... SELECT per kind with ON CONFLICT DO NOTHING on the per-user dedupe
key, so it is idempotent: running it twice, or in two processes at once,
records each occurrence once.

Reads use one REPEATABLE READ, READ ONLY transaction per response. Links are
returned only after checking, in that transaction, that the record exists and
belongs to the caller."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    String,
    cast,
    extract,
    func,
    literal,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.expression import Selectable

from app.agents.models import AgentEvent
from app.alerts.catalog import CATALOG, SEVERITIES, Severity, Source
from app.alerts.models import Alert, AlertPreference
from app.alerts.schemas import (
    AlertInAppOut,
    AlertLinkOut,
    AlertOut,
    AlertPageOut,
    AlertPreferencesIn,
    AlertPreferencesOut,
    AlertUnreadOut,
)
from app.auth.models import AuditEvent
from app.auth.models import Session as SessionRow
from app.brokers.models import BrokerConnection
from app.core.errors import ApiError
from app.db.session import begin_consistent_read
from app.paper.models import PaperOrder, PaperReplay, PaperTrade

logger = structlog.get_logger(__name__)

MAX_SEQ = 2**63 - 1  # PostgreSQL bigint
_CURSOR = re.compile(r"v1:([0-9a-f]{16}):([1-9][0-9]{0,18})")
_EXPIRED = CATALOG["BROKER_CONNECTION_EXPIRED"]
_MISMATCH = CATALOG["RECONCILIATION_MISMATCH"]


def unavailable() -> ApiError:
    return ApiError(
        503, "ALERTS_UNAVAILABLE", "Alerts are temporarily unavailable. Try again shortly."
    )


def invalid_cursor() -> ApiError:
    return ApiError(
        400, "INVALID_REQUEST", "The page cursor is invalid. Start from the first page."
    )


def not_found() -> ApiError:
    return ApiError(404, "ALERT_NOT_FOUND", "This alert was not found.")


def _fingerprint(
    severities: Sequence[Severity], sources: Sequence[Source], unread: bool, shown: Sequence[str]
) -> str:
    """Identifies the filters and preferences a cursor was issued under."""
    canonical = "|".join(
        [
            ",".join(sorted(severities)),
            ",".join(sorted(sources)),
            "unread" if unread else "all",
            ",".join(sorted(shown)),
        ]
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def encode_cursor(fingerprint: str, seq: int) -> str:
    raw = f"v1:{fingerprint}:{seq}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, fingerprint: str) -> int:
    """The sequence a cursor continues before. Raises 400 when it is malformed
    or was issued under other filters or preferences."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise invalid_cursor() from None
    match = _CURSOR.fullmatch(raw)
    if (
        match is None
        or match.group(1) != fingerprint
        or encode_cursor(fingerprint, int(match.group(2))) != cursor
    ):
        raise invalid_cursor()
    seq = int(match.group(2))
    if seq > MAX_SEQ:
        raise invalid_cursor()
    return seq


class AlertService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime],
        enabled: bool = True,
    ) -> None:
        self._factory = session_factory
        self._clock = clock
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise unavailable()

    # ----------------------------------------------------------------- reads

    async def page(
        self,
        user_id: uuid.UUID,
        *,
        severities: Sequence[Severity],
        sources: Sequence[Source],
        unread: bool,
        cursor: str | None,
        limit: int,
    ) -> AlertPageOut:
        self._require_enabled()
        async with self._factory() as db, db.begin():
            await begin_consistent_read(db)
            now = self._clock()
            prefs = await db.get(AlertPreference, user_id)
            shown = _shown(prefs)
            fingerprint = _fingerprint(severities, sources, unread, shown)
            before = None if cursor is None else decode_cursor(cursor, fingerprint)
            query = select(Alert).where(Alert.user_id == user_id, Alert.severity.in_(shown))
            if severities:
                query = query.where(Alert.severity.in_(severities))
            if sources:
                query = query.where(Alert.source.in_(sources))
            if unread:
                query = query.where(Alert.acknowledged_at.is_(None))
            if before is not None:
                query = query.where(Alert.seq < before)
            rows = list((await db.scalars(query.order_by(Alert.seq.desc()).limit(limit + 1))).all())
            page = rows[:limit]
            verified = await _verified_links(db, user_id, page)
            count_rows = await db.execute(
                select(Alert.severity, func.count())
                .where(
                    Alert.user_id == user_id,
                    Alert.acknowledged_at.is_(None),
                    Alert.severity.in_(shown),
                )
                .group_by(Alert.severity)
            )
            counts = {severity: int(n) for severity, n in count_rows}
        unread_counts = {severity: int(counts.get(severity, 0)) for severity in SEVERITIES}
        return AlertPageOut(
            as_of=now,
            items=[_alert_out(row, verified) for row in page],
            next_cursor=encode_cursor(fingerprint, page[-1].seq) if len(rows) > limit else None,
            unread=AlertUnreadOut(total=sum(unread_counts.values()), **unread_counts),
        )

    async def acknowledge(self, user_id: uuid.UUID, alert_id: str) -> AlertOut:
        self._require_enabled()
        try:
            key = uuid.UUID(alert_id)
        except ValueError:
            raise not_found() from None
        async with self._factory() as db:
            async with db.begin():
                # Only the first acknowledgement writes; the row lock makes a
                # concurrent one wait and then match nothing.
                await db.execute(
                    update(Alert)
                    .where(
                        Alert.id == key,
                        Alert.user_id == user_id,
                        Alert.acknowledged_at.is_(None),
                    )
                    .values(acknowledged_at=self._clock())
                )
            async with db.begin():
                row = await db.scalar(
                    select(Alert)
                    .where(Alert.id == key, Alert.user_id == user_id)
                    .execution_options(populate_existing=True)
                )
                if row is None:
                    raise not_found()
                verified = await _verified_links(db, user_id, [row])
        return _alert_out(row, verified)

    async def preferences(self, user_id: uuid.UUID) -> AlertPreferencesOut:
        self._require_enabled()
        async with self._factory() as db, db.begin():
            prefs = await db.get(AlertPreference, user_id)
        return _preferences_out(prefs)

    async def save_preferences(
        self, user_id: uuid.UUID, body: AlertPreferencesIn
    ) -> AlertPreferencesOut:
        self._require_enabled()
        async with self._factory() as db, db.begin():
            # Serialises saves for one user, including the first (no row to lock yet).
            await db.execute(
                select(func.pg_advisory_xact_lock(func.hashtextextended(f"alerts:{user_id}", 0)))
            )
            now = self._clock()
            prefs = await db.get(AlertPreference, user_id, populate_existing=True)
            before = _preferences_out(prefs).in_app
            if prefs is None:
                prefs = AlertPreference(
                    user_id=user_id,
                    warning=body.in_app.warning,
                    info=body.in_app.info,
                    updated_at=now,
                )
                db.add(prefs)
                changed = body.in_app.warning is not True or body.in_app.info is not True
            else:
                changed = (prefs.warning, prefs.info) != (body.in_app.warning, body.in_app.info)
                if changed:
                    prefs.warning = body.in_app.warning
                    prefs.info = body.in_app.info
                    prefs.updated_at = now
            if changed:
                db.add(
                    AuditEvent(
                        user_id=user_id,
                        actor=f"user:{user_id}",
                        action="alerts.preferences",
                        resource=f"alerts:{user_id}",
                        metadata_redacted={
                            "before": {"warning": before.warning, "info": before.info},
                            "after": {"warning": body.in_app.warning, "info": body.in_app.info},
                        },
                        created_at=now,
                    )
                )
            await db.flush()
            out = _preferences_out(prefs)
        return out

    # ---------------------------------------------------------------- worker

    async def run_once(self) -> int:
        """Record alerts for expired broker connections and reconciliation
        mismatches not yet alerted. Returns how many were recorded."""
        async with self._factory() as db, db.begin():
            now = self._clock()
            expired = await db.execute(
                insert(Alert)
                .from_select(
                    _COLUMNS,
                    _expired_connections(now),
                )
                .on_conflict_do_nothing(constraint="uq_alerts_dedupe")
            )
            mismatches = await db.execute(
                insert(Alert)
                .from_select(_COLUMNS, _reconciliation_mismatches(now))
                .on_conflict_do_nothing(constraint="uq_alerts_dedupe")
            )
        return int(expired.rowcount or 0) + int(mismatches.rowcount or 0)  # type: ignore[attr-defined]

    async def run_worker(self, poll_seconds: float) -> None:
        """Record worker alerts until cancelled, checking every `poll_seconds`."""
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The database may be briefly down; try again on the next poll.
                logger.warning("alert_worker_error", error_type=type(exc).__name__)
            await asyncio.sleep(poll_seconds)


_COLUMNS = [
    "user_id",
    "dedupe_key",
    "kind",
    "source",
    "severity",
    "environment",
    "title",
    "message",
    "link_kind",
    "link_id",
    "occurred_at",
    "created_at",
]


def _not_alerted(user_id: Any, dedupe_key: Any) -> ColumnElement[bool]:
    return (
        ~select(Alert.id).where(Alert.user_id == user_id, Alert.dedupe_key == dedupe_key).exists()
    )


def _expired_connections(now: datetime) -> Selectable:
    # One alert per connection and expiry: a reconnect sets a new expiry.
    expiry_us = cast(extract("epoch", BrokerConnection.expires_at) * 1_000_000, BigInteger)
    dedupe = func.concat(
        "broker-expired:", cast(BrokerConnection.id, String), ":", cast(expiry_us, String)
    )
    return select(
        BrokerConnection.user_id,
        dedupe,
        literal("BROKER_CONNECTION_EXPIRED"),
        literal(_EXPIRED.source),
        literal(_EXPIRED.severity),
        literal(_EXPIRED.environment),
        literal(_EXPIRED.title),
        func.concat(
            "The demo ",
            BrokerConnection.provider,
            " connection expired. Reconnect it to sync again.",
        ),
        literal("broker"),
        BrokerConnection.provider,
        BrokerConnection.expires_at,
        literal(now),
    ).where(
        BrokerConnection.expires_at <= now,
        _not_alerted(BrokerConnection.user_id, dedupe),
    )


def _reconciliation_mismatches(now: datetime) -> Selectable:
    dedupe = func.concat("agent-event:", cast(AgentEvent.id, String))
    return select(
        AgentEvent.user_id,
        dedupe,
        literal("RECONCILIATION_MISMATCH"),
        literal(_MISMATCH.source),
        literal(_MISMATCH.severity),
        literal(_MISMATCH.environment),
        literal(_MISMATCH.title),
        func.left(AgentEvent.message, 500),
        AgentEvent.link_kind,
        AgentEvent.link_id,
        AgentEvent.created_at,
        literal(now),
    ).where(
        AgentEvent.agent_id == "execution-monitor",
        AgentEvent.reason_code == "RECONCILIATION_MISMATCH",
        _not_alerted(AgentEvent.user_id, dedupe),
    )


def _shown(prefs: AlertPreference | None) -> list[str]:
    shown = ["critical"]
    if prefs is None or prefs.warning:
        shown.append("warning")
    if prefs is None or prefs.info:
        shown.append("info")
    return shown


def _preferences_out(prefs: AlertPreference | None) -> AlertPreferencesOut:
    return AlertPreferencesOut(
        in_app=AlertInAppOut(
            warning=True if prefs is None else prefs.warning,
            info=True if prefs is None else prefs.info,
        ),
        updated_at=None if prefs is None else prefs.updated_at,
    )


def _alert_out(row: Alert, verified: set[tuple[str, str]]) -> AlertOut:
    link = (
        AlertLinkOut(kind=row.link_kind, id=row.link_id)
        if row.link_kind is not None
        and row.link_id is not None
        and (row.link_kind, row.link_id) in verified
        else None
    )
    return AlertOut(
        id=str(row.id),
        kind=row.kind,
        source=row.source,
        severity=row.severity,
        environment=row.environment,
        title=row.title,
        message=row.message,
        occurred_at=row.occurred_at,
        created_at=row.created_at,
        acknowledged_at=row.acknowledged_at,
        link=link,
    )


async def _verified_links(
    db: AsyncSession, user_id: uuid.UUID, rows: Sequence[Alert]
) -> set[tuple[str, str]]:
    """(kind, id) pairs among `rows`' links whose record exists and is the user's."""
    wanted: dict[str, set[str]] = {}
    for row in rows:
        if row.link_kind is not None and row.link_id is not None:
            wanted.setdefault(row.link_kind, set()).add(row.link_id)
    found: set[tuple[str, str]] = set()
    for kind, model in (
        ("paper-trade", PaperTrade),
        ("paper-order", PaperOrder),
        ("session", SessionRow),
    ):
        ids = [i for i in (_uuid(v) for v in wanted.get(kind, ())) if i is not None]
        if ids:
            matched = await db.scalars(
                select(model.id).where(model.user_id == user_id, model.id.in_(ids))
            )
            found |= {(kind, str(i)) for i in matched}
    replays = [int(v) for v in wanted.get("paper-replay", ()) if v.isdigit() and len(v) <= 9]
    if replays:
        matched_replays = await db.scalars(
            select(PaperReplay.replay).where(
                PaperReplay.user_id == user_id, PaperReplay.replay.in_(replays)
            )
        )
        found |= {("paper-replay", str(r)) for r in matched_replays}
    providers = sorted(wanted.get("broker", ()))
    if providers:
        matched_providers = await db.scalars(
            select(BrokerConnection.provider).where(
                BrokerConnection.user_id == user_id, BrokerConnection.provider.in_(providers)
            )
        )
        found |= {("broker", p) for p in matched_providers}
    return found


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
