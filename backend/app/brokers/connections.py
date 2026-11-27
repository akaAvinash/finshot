"""Provider-neutral broker connections (contract 0.11.0, tag Broker connections).

Demo only and read-only. Authorization has two steps: `start` stores a hash of
a single-use `state` bound to the caller's session; `complete` checks it,
exchanges the provider's returned parameters outside any database transaction,
then claims the state and writes under a per-(user, provider) advisory lock
(the lock the deprecated preview service also takes). Every applied action
appends one broker event and one audit event in the same transaction."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, cast

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerts import producer as alerts
from app.auth.models import AuditEvent
from app.brokers.adapter import (
    BrokerAdapter,
    BrokerAuthInvalidError,
    BrokerAuthorizationFailedError,
    BrokerCapabilityUnsupportedError,
    BrokerMalformedResponseError,
    BrokerRateLimitedError,
    BrokerUnavailableError,
    Capability,
    PortfolioData,
    ProviderSpec,
)
from app.brokers.connection_schemas import (
    MAX_EVENTS,
    AuthorizationOut,
    AuthorizationResultOut,
    ConnectionAction,
    ConnectionOut,
    EventOut,
    PortfolioOut,
    ProviderOut,
    SnapshotOut,
)
from app.brokers.models import BrokerAuthorization, BrokerConnection, BrokerEvent
from app.core.errors import ApiError
from app.db.session import begin_consistent_read

logger = structlog.get_logger(__name__)

AUTHORIZATION_TTL = timedelta(minutes=10)
_STALE_AFTER = timedelta(days=1)


def unavailable() -> ApiError:
    return ApiError(
        503, "BROKER_UNAVAILABLE", "Broker accounts are temporarily unavailable. Try again shortly."
    )


def not_found() -> ApiError:
    return ApiError(404, "BROKER_CONNECTION_NOT_FOUND", "This broker connection no longer exists.")


def conflict() -> ApiError:
    return ApiError(
        409, "BROKER_ACTION_CONFLICT", "This broker account is not ready for that action."
    )


def authorization_invalid() -> ApiError:
    return ApiError(
        400, "BROKER_AUTHORIZATION_INVALID", "This broker sign-in has expired. Start again."
    )


def _provider_unavailable() -> ApiError:
    return ApiError(400, "BROKER_PROVIDER_UNAVAILABLE", "This broker is not available.")


def _limit() -> ApiError:
    return ApiError(
        409,
        "BROKER_CONNECTION_LIMIT",
        "You already have the maximum number of connections for this broker.",
    )


def _auth_expired() -> ApiError:
    return ApiError(
        409, "BROKER_AUTH_EXPIRED", "This broker sign-in has expired. Reconnect to continue."
    )


def _provider_error(exc: Exception) -> ApiError:
    """Map an adapter failure to a contract error without leaking its text."""
    if isinstance(exc, BrokerRateLimitedError):
        return ApiError(
            429,
            "BROKER_RATE_LIMITED",
            "The broker is busy. Try again shortly.",
            retry_after_seconds=max(1, exc.retry_after_seconds),
        )
    if isinstance(exc, BrokerMalformedResponseError):
        return ApiError(
            502,
            "BROKER_MALFORMED_RESPONSE",
            "The broker sent an unexpected response. Try again later.",
        )
    if isinstance(exc, BrokerCapabilityUnsupportedError):
        return ApiError(409, "BROKER_CAPABILITY_UNSUPPORTED", "This broker does not support that.")
    return unavailable()


def hash_state(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def status_of(row: BrokerConnection, now: datetime) -> tuple[str, str | None]:
    """(status, statusReason). A provider-reported invalidation wins over time."""
    if row.status_reason is not None:
        return "expired", row.status_reason
    if now >= row.expires_at:
        return "expired", "EXPIRED"
    return "connected", None


class BrokerConnectionService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        adapter: BrokerAdapter | None,
        clock: Callable[[], datetime],
        timeout_seconds: float,
        callback_path: str,
    ) -> None:
        """`adapter=None` means BROKER_PROVIDER=disabled: every call is 503."""
        self._factory = session_factory
        self._adapter = adapter
        self._clock = clock
        self._timeout = timeout_seconds
        self._callback_path = callback_path
        # Test seam: after the provider exchange, before the state is claimed.
        self._after_exchange: Callable[[], None] | None = None

    def _require_adapter(self) -> BrokerAdapter:
        if self._adapter is None:
            raise unavailable()
        return self._adapter

    # --- reads ---------------------------------------------------------------

    async def snapshot(self, user_id: uuid.UUID) -> SnapshotOut:
        adapter = self._require_adapter()
        async with self._factory() as db:
            return await self._snapshot(db, adapter, user_id, self._clock())

    async def portfolio(self, user_id: uuid.UUID, connection_id: uuid.UUID) -> PortfolioOut:
        self._require_adapter()
        async with self._factory() as db, db.begin():
            row = await _owned(db, user_id, connection_id)
        if row is None:
            raise not_found()
        stored = row.portfolio
        sections: dict[str, Any] = {}
        for name, capability in _SECTIONS.items():
            if capability not in row.scopes:
                sections[name] = None
            elif stored is None:
                # Before the first sync: empty lists, no funds.
                sections[name] = None if name == "funds" else []
            else:
                sections[name] = stored.get(name)
        return PortfolioOut(connection_id=row.id, as_of=row.last_synced_at, **sections)

    # --- step 1 ----------------------------------------------------------------

    async def start_authorization(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        provider_id: str | None,
        connection_id: uuid.UUID | None,
    ) -> AuthorizationOut:
        adapter = self._require_adapter()
        now = self._clock()
        async with self._factory() as db, db.begin():
            if connection_id is not None:
                row = await _owned(db, user_id, connection_id)
                if row is None:
                    raise not_found()
                provider = row.provider
                spec = _spec(adapter, provider)
                if spec is None or not spec.available:
                    raise _provider_unavailable()
            else:
                spec = _spec(adapter, provider_id or "")
                if spec is None or not spec.available:
                    raise _provider_unavailable()
                provider = spec.id
                held = await db.scalar(
                    select(func.count())
                    .select_from(BrokerConnection)
                    .where(
                        BrokerConnection.user_id == user_id, BrokerConnection.provider == provider
                    )
                )
                if (held or 0) >= spec.max_connections:
                    raise _limit()
            state = secrets.token_urlsafe(32)
            authorization_id = uuid.uuid4()
            expires_at = now + AUTHORIZATION_TTL
            await db.execute(
                delete(BrokerAuthorization).where(
                    BrokerAuthorization.user_id == user_id,
                    BrokerAuthorization.expires_at < now - _STALE_AFTER,
                )
            )
            db.add(
                BrokerAuthorization(
                    id=authorization_id,
                    user_id=user_id,
                    session_id=session_id,
                    provider=provider,
                    connection_id=connection_id,
                    state_hash=hash_state(state),
                    created_at=now,
                    expires_at=expires_at,
                )
            )
            url = adapter.authorize_url(provider, state, self._callback_path)
        return AuthorizationOut(
            authorization_id=authorization_id,
            provider_id=provider,
            authorize_url=url,
            expires_at=expires_at,
        )

    # --- step 2 ----------------------------------------------------------------

    async def complete_authorization(
        self,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        *,
        state: str,
        params: Mapping[str, str],
    ) -> AuthorizationResultOut:
        adapter = self._require_adapter()
        now = self._clock()
        state_hash = hash_state(state)
        # Cheap pre-check, so a bad state never reaches the provider.
        async with self._factory() as db, db.begin():
            pending = await _pending(db, user_id, session_id, state_hash, now)
            if pending is None:
                raise authorization_invalid()
            provider, bound_connection = pending.provider, pending.connection_id
        try:
            async with asyncio.timeout(self._timeout):
                grant = await adapter.exchange(provider, params, now)
        except (BrokerAuthorizationFailedError, BrokerAuthInvalidError):
            # The provider rejected the parameters: the state is spent.
            async with self._factory() as db, db.begin():
                await _claim(db, user_id, session_id, state_hash, now)
            raise authorization_invalid() from None
        except (
            BrokerUnavailableError,
            BrokerRateLimitedError,
            BrokerMalformedResponseError,
            BrokerCapabilityUnsupportedError,
        ) as exc:
            logger.warning("broker_exchange_failed", provider=provider, error=type(exc).__name__)
            raise _provider_error(exc) from None
        except TimeoutError:
            logger.warning("broker_exchange_timeout", provider=provider)
            raise unavailable() from None
        if self._after_exchange is not None:
            self._after_exchange()
        spec = _spec(adapter, provider)
        max_connections = spec.max_connections if spec else 1
        async with self._factory() as db:
            async with db.begin():
                await _lock(db, user_id, provider)
                if not await _claim(db, user_id, session_id, state_hash, now):
                    raise authorization_invalid()
                account_ref = grant.account_ref or grant.masked_account_id
                row: BrokerConnection | None
                if bound_connection is not None:
                    row = await _owned(db, user_id, bound_connection)
                    if row is None or row.account_ref != account_ref:
                        raise conflict()
                    action = "reconnect"
                else:
                    row = await db.scalar(
                        select(BrokerConnection).where(
                            BrokerConnection.user_id == user_id,
                            BrokerConnection.provider == provider,
                            BrokerConnection.account_ref == account_ref,
                        )
                    )
                    action = "reconnect" if row is not None else "connect"
                    if row is None:
                        held = await db.scalar(
                            select(func.count())
                            .select_from(BrokerConnection)
                            .where(
                                BrokerConnection.user_id == user_id,
                                BrokerConnection.provider == provider,
                            )
                        )
                        if (held or 0) >= max_connections:
                            raise _limit()
                        row = BrokerConnection(id=uuid.uuid4(), user_id=user_id, provider=provider)
                        db.add(row)
                row.account_ref = account_ref
                row.masked_account_id = grant.masked_account_id
                row.scopes = list(grant.scopes)
                row.connected_at = now
                row.expires_at = grant.expires_at
                row.last_synced_at = None
                row.status_reason = None
                row.portfolio = None
                await db.flush()
                connection_id = row.id
                _record(db, user_id, connection_id, provider, action, now)
        async with self._factory() as fresh:
            snapshot = await self._snapshot(fresh, adapter, user_id, self._clock())
        return AuthorizationResultOut(connection_id=connection_id, snapshot=snapshot)

    # --- actions -----------------------------------------------------------------

    async def apply(
        self, user_id: uuid.UUID, connection_id: uuid.UUID, action: ConnectionAction
    ) -> SnapshotOut:
        adapter = self._require_adapter()
        async with self._factory() as db, db.begin():
            first = await _owned(db, user_id, connection_id)
            if first is None:
                raise not_found()
            provider = first.provider
            seen = (first.account_ref, list(first.scopes), first.connected_at)
            if action == "sync" and status_of(first, self._clock())[0] != "connected":
                raise conflict()
        if action == "sync":
            await self._sync(adapter, user_id, connection_id, provider, seen)
            revoke_ref: str | None = None
        else:
            revoke_ref = await self._disconnect(user_id, connection_id, provider)
        if revoke_ref is not None:
            await self._revoke(adapter, provider, revoke_ref)
        async with self._factory() as fresh:
            return await self._snapshot(fresh, adapter, user_id, self._clock())

    async def _sync(
        self,
        adapter: BrokerAdapter,
        user_id: uuid.UUID,
        connection_id: uuid.UUID,
        provider: str,
        seen: tuple[str, list[str], datetime],
    ) -> None:
        """The provider call holds no transaction and no lock. The write then
        re-reads the row under the lock and keeps the result only if the same
        authorization is still connected (a re-authorization or disconnect in
        between makes this a conflict and discards the fetch)."""
        account_ref, scopes, connected_at = seen
        invalidated = False
        data: PortfolioData | None = None
        try:
            async with asyncio.timeout(self._timeout):
                data = await adapter.fetch_portfolio(
                    provider, account_ref, cast(list[Capability], scopes), self._clock()
                )
            if data.account_ref != account_ref:
                raise BrokerMalformedResponseError("account mismatch")
        except BrokerAuthInvalidError:
            invalidated = True
        except (
            BrokerUnavailableError,
            BrokerRateLimitedError,
            BrokerMalformedResponseError,
            BrokerCapabilityUnsupportedError,
        ) as exc:
            logger.warning("broker_sync_failed", provider=provider, error=type(exc).__name__)
            raise _provider_error(exc) from None
        except TimeoutError:
            logger.warning("broker_sync_timeout", provider=provider)
            raise unavailable() from None
        async with self._factory() as db:
            async with db.begin():
                await _lock(db, user_id, provider)
                now = self._clock()
                row = await _owned(db, user_id, connection_id)
                if (
                    row is None
                    or row.connected_at != connected_at
                    or row.account_ref != account_ref
                    or status_of(row, now)[0] != "connected"
                ):
                    raise conflict()
                if invalidated:
                    # Keep the status change: commit it, then answer 409.
                    row.status_reason = "AUTH_INVALIDATED"
                    _record(db, user_id, row.id, provider, "expire", now)
                    await alerts.record(
                        db,
                        user_id=user_id,
                        kind="BROKER_CONNECTION_EXPIRED",
                        dedupe_key=f"broker-invalidated:{row.id}:{now.isoformat()}",
                        message=f"The demo {provider} sign-in was ended by the broker. "
                        "Reconnect it to sync again.",
                        at=now,
                        link=("broker-connection", str(row.id)),
                    )
                elif data is not None:
                    row.portfolio = _stored(data, scopes)
                    row.last_synced_at = now
                    _record(db, user_id, row.id, provider, "sync", now)
        if invalidated:
            raise _auth_expired()

    async def _disconnect(self, user_id: uuid.UUID, connection_id: uuid.UUID, provider: str) -> str:
        async with self._factory() as db:
            async with db.begin():
                await _lock(db, user_id, provider)
                now = self._clock()
                row = await _owned(db, user_id, connection_id)
                if row is None:
                    raise not_found()
                account_ref = row.account_ref
                event_id = _record(db, user_id, row.id, provider, "disconnect", now)
                await alerts.record(
                    db,
                    user_id=user_id,
                    kind="BROKER_DISCONNECTED",
                    dedupe_key=f"broker-disconnected:{event_id}",
                    message=f"The demo {provider} connection was disconnected.",
                    at=now,
                    link=("broker-connection", str(row.id)),
                )
                await db.execute(
                    delete(BrokerConnection).where(
                        BrokerConnection.user_id == user_id, BrokerConnection.id == row.id
                    )
                )
        return account_ref

    async def _revoke(self, adapter: BrokerAdapter, provider: str, account_ref: str) -> None:
        """Best effort: a failed revoke is logged and never blocks a disconnect."""
        try:
            async with asyncio.timeout(self._timeout):
                await adapter.revoke(provider, account_ref)
        except Exception as exc:
            logger.warning("broker_revoke_failed", provider=provider, error=type(exc).__name__)

    # --- snapshot ------------------------------------------------------------------

    async def _snapshot(
        self, db: AsyncSession, adapter: BrokerAdapter, user_id: uuid.UUID, now: datetime
    ) -> SnapshotOut:
        async with db.begin():
            await begin_consistent_read(db)
            rows = (
                await db.scalars(
                    select(BrokerConnection)
                    .where(BrokerConnection.user_id == user_id)
                    .order_by(BrokerConnection.connected_at, BrokerConnection.id)
                )
            ).all()
            events = (
                await db.scalars(
                    select(BrokerEvent)
                    .where(BrokerEvent.user_id == user_id)
                    .order_by(BrokerEvent.seq.desc())
                    .limit(MAX_EVENTS)
                )
            ).all()
        connections = []
        for row in rows:
            status, reason = status_of(row, now)
            connections.append(
                ConnectionOut(
                    connection_id=row.id,
                    provider_id=row.provider,
                    status=status,
                    status_reason=reason,
                    masked_account_id=row.masked_account_id,
                    capabilities=cast(list[Capability], list(row.scopes)),
                    connected_at=row.connected_at,
                    expires_at=row.expires_at,
                    last_synced_at=row.last_synced_at,
                )
            )
        return SnapshotOut(
            as_of=now,
            providers=[
                ProviderOut(
                    id=p.id,
                    display_name=p.display_name,
                    capabilities=list(p.capabilities),
                    max_connections=p.max_connections,
                    available=p.available,
                )
                for p in adapter.providers()
            ],
            connections=connections,
            events=[
                EventOut(
                    id=str(e.id),
                    connection_id=e.connection_id,
                    provider_id=e.provider,
                    action=e.action,
                    at=e.at,
                )
                for e in reversed(events)
            ],
        )


_SECTIONS = {
    "holdings": "holdings_read",
    "positions": "positions_read",
    "orders": "orders_read",
    "funds": "funds_read",
}


def _stored(data: PortfolioData, granted: list[str]) -> dict[str, Any]:
    """The sections to keep: only those whose capability is granted."""
    values = {
        "holdings": data.holdings,
        "positions": data.positions,
        "orders": data.orders,
        "funds": data.funds,
    }
    return {name: (values[name] if cap in granted else None) for name, cap in _SECTIONS.items()}


def _spec(adapter: BrokerAdapter, provider: str) -> ProviderSpec | None:
    return next((p for p in adapter.providers() if p.id == provider), None)


def _record(
    db: AsyncSession,
    user_id: uuid.UUID,
    connection_id: uuid.UUID,
    provider: str,
    action: str,
    now: datetime,
) -> uuid.UUID:
    event_id = uuid.uuid4()
    db.add(
        BrokerEvent(
            id=event_id,
            user_id=user_id,
            connection_id=connection_id,
            provider=provider,
            action=action,
            at=now,
        )
    )
    if action != "expire":
        db.add(
            AuditEvent(
                user_id=user_id,
                actor=f"user:{user_id}",
                action=f"broker.{action}",
                resource=f"broker:{provider}",
                metadata_redacted={"environment": "DEMO", "connectionId": str(connection_id)},
                created_at=now,
            )
        )
    return event_id


async def _owned(
    db: AsyncSession, user_id: uuid.UUID, connection_id: uuid.UUID
) -> BrokerConnection | None:
    return await db.scalar(
        select(BrokerConnection).where(
            BrokerConnection.user_id == user_id, BrokerConnection.id == connection_id
        )
    )


async def _lock(db: AsyncSession, user_id: uuid.UUID, provider: str) -> None:
    # The same key the deprecated preview service takes, so the two never interleave.
    await db.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"broker:{user_id}:{provider}", 0)))
    )


async def _pending(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    state_hash: str,
    now: datetime,
) -> BrokerAuthorization | None:
    return await db.scalar(
        select(BrokerAuthorization).where(
            BrokerAuthorization.state_hash == state_hash,
            BrokerAuthorization.user_id == user_id,
            BrokerAuthorization.session_id == session_id,
            BrokerAuthorization.used_at.is_(None),
            BrokerAuthorization.expires_at > now,
        )
    )


async def _claim(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    state_hash: str,
    now: datetime,
) -> bool:
    """Mark the state used. False when another request already did, or it expired."""
    result = await db.execute(
        update(BrokerAuthorization)
        .where(
            BrokerAuthorization.state_hash == state_hash,
            BrokerAuthorization.user_id == user_id,
            BrokerAuthorization.session_id == session_id,
            BrokerAuthorization.used_at.is_(None),
            BrokerAuthorization.expires_at > now,
        )
        .values(used_at=now)
        .returning(BrokerAuthorization.id)
    )
    return result.first() is not None
