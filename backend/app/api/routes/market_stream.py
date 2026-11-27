"""/api/v1/market/stream: the owner-only, read-only market WebSocket, as
specified in contracts/live-market-stream.asyncapi.yaml.

Before the upgrade, checks run in this order and fail with an HTTP response
in the shared error shape: 404 when the stream is disabled, 403 for an Origin
other than PUBLIC_ORIGIN, 401 for a missing, expired or revoked session, 403
for any account other than the configured owner (tester sessions and
sessions pending authenticator setup included), 400 for invalid selection
parameters, 503 when the feed cannot serve a snapshot or the connection cap
is reached, or the session cannot be checked (database down).

After the upgrade the server sends a snapshot, then updates and status
frames. The session is checked again every MARKET_STREAM_SESSION_RECHECK_SECONDS, and
each check renews it (owner decision: an open chart keeps the session alive
until its absolute expiry): 4401 when it has ended,
4403 when the account is no longer eligible. A client that falls behind, or a
recheck that cannot reach the database, is closed with 1013, and a client
that sends any message with 1008."""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

from app.auth.cookies import SESSION_COOKIE
from app.auth.service import AuthService, SessionInfo
from app.core.config import Settings
from app.market.schemas import INSTRUMENT_ID_PATTERN, TIMEFRAMES, MarketCandle, MarketCandles
from app.market.stream.hub import MarketStreamHub, Subscriber
from app.market.stream.messages import (
    MarketSnapshotFrame,
    MarketStatusFrame,
    MarketUpdateFrame,
    wire,
)
from app.market.stream.ticks import CandleBuilder, FeedState, Tick, quote_from_tick

router = APIRouter(prefix="/api/v1/market", tags=["market"])
logger = structlog.get_logger(__name__)

CLOSE_NORMAL = 1000
CLOSE_POLICY = 1008
CLOSE_OVERLOADED = 1013
CLOSE_SESSION_ENDED = 4401
CLOSE_FORBIDDEN = 4403

_INSTRUMENT = re.compile(INSTRUMENT_ID_PATTERN)
_QUERY_KEYS = {"instrumentId", "timeframe"}


class _Denied(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after


def _eligible(settings: Settings, session: SessionInfo) -> bool:
    return (
        session.access == "regular"
        and session.totp_enabled
        and session.user_id == settings.market_stream_owner_user_id
    )


def _selection(websocket: WebSocket, hub: MarketStreamHub) -> tuple[str, Any]:
    items = websocket.query_params.multi_items()
    invalid = _Denied(400, "INVALID_REQUEST", "The request parameters are invalid.")
    keys = [key for key, _ in items]
    if set(keys) != _QUERY_KEYS or len(keys) != len(_QUERY_KEYS):
        raise invalid  # missing, unknown or repeated parameters
    params = dict(items)
    instrument_id = params["instrumentId"]
    timeframe = params["timeframe"]
    if not _INSTRUMENT.fullmatch(instrument_id) or timeframe not in TIMEFRAMES:
        raise invalid
    if instrument_id not in hub.source.instrument_ids():
        raise invalid
    return instrument_id, timeframe


def _unavailable() -> _Denied:
    return _Denied(
        503,
        "MARKET_STREAM_UNAVAILABLE",
        "The market stream is temporarily unavailable. Try again shortly.",
        retry_after=5,
    )


async def _deny(websocket: WebSocket, denied: _Denied) -> None:
    body: dict[str, Any] = {"code": denied.code, "message": denied.message}
    headers: dict[str, str] = {}
    if denied.retry_after is not None:
        body["retryAfterSeconds"] = denied.retry_after
        headers["Retry-After"] = str(denied.retry_after)
    response = JSONResponse(status_code=denied.status, content=body, headers=headers)
    try:
        await websocket.send_denial_response(response)
    except RuntimeError:
        # A server without the denial-response extension can only refuse the
        # upgrade (the client sees 403).
        await websocket.close(code=CLOSE_POLICY)


async def _authorize(
    websocket: WebSocket, settings: Settings, auth: AuthService
) -> tuple[str, SessionInfo]:
    if websocket.headers.get("origin") != settings.public_origin:
        raise _Denied(403, "ORIGIN_NOT_ALLOWED", "This origin may not open the market stream.")
    token = websocket.cookies.get(SESSION_COOKIE)
    try:
        session = await auth.resolve_session(token)
    except Exception as exc:  # database or cache down: fail closed, as unavailable
        logger.warning("market_stream_session_check_failed", error_type=type(exc).__name__)
        raise _unavailable() from exc
    if token is None or session is None:
        raise _Denied(401, "UNAUTHENTICATED", "Sign in to continue.")
    if not _eligible(settings, session):
        raise _Denied(
            403, "MARKET_STREAM_FORBIDDEN", "This account may not open the market stream."
        )
    return token, session


async def _snapshot(
    hub: MarketStreamHub, settings: Settings, instrument_id: str, timeframe: Any
) -> tuple[MarketSnapshotFrame, Tick]:
    timeout = settings.market_stream_snapshot_timeout_seconds
    tick = await hub.wait_for_tick(instrument_id, wait_seconds=timeout)
    if tick is None or hub.state() == "unavailable":
        raise _unavailable()
    try:
        async with asyncio.timeout(timeout):
            candles = await hub.source.history(instrument_id, timeframe)
        frame = MarketSnapshotFrame(
            as_of=tick.exchange_time,
            quote=quote_from_tick(tick),
            history=MarketCandles(
                instrument_id=instrument_id,
                timeframe=timeframe,
                source="market",
                as_of=tick.exchange_time,
                freshness="fresh" if hub.state() in ("live", "closed") else "stale",
                candles=candles,
            ),
        )
    except Exception as exc:  # timeout, provider outage or invalid data: all 503
        logger.warning("market_stream_snapshot_failed", error_type=type(exc).__name__)
        raise _unavailable() from exc
    return frame, tick


@router.websocket("/stream")
async def market_stream(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings
    hub: MarketStreamHub | None = getattr(websocket.app.state, "market_stream", None)
    auth: AuthService = websocket.app.state.auth
    try:
        if not settings.market_stream_enabled or hub is None:
            raise _Denied(404, "NOT_FOUND", "API endpoint not found.")
        token, _ = await _authorize(websocket, settings, auth)
        instrument_id, timeframe = _selection(websocket, hub)
    except _Denied as denied:
        await _deny(websocket, denied)
        return

    async with hub.subscribe(instrument_id) as subscriber:
        try:
            if hub.connection_count > settings.market_stream_max_connections:
                raise _unavailable()
            frame, tick = await _snapshot(hub, settings, instrument_id, timeframe)
        except _Denied as denied:
            await _deny(websocket, denied)
            return
        await websocket.accept()
        logger.info("market_stream_opened", instrument_id=instrument_id, timeframe=timeframe)
        code = CLOSE_NORMAL
        try:
            code = await _serve(
                websocket, hub, subscriber, settings, auth, token, frame, tick, timeframe
            )
        except (WebSocketDisconnect, OSError):
            code = 1006
        finally:
            logger.info("market_stream_closed", instrument_id=instrument_id, code=code)


async def _serve(
    websocket: WebSocket,
    hub: MarketStreamHub,
    subscriber: Subscriber,
    settings: Settings,
    auth: AuthService,
    token: str,
    snapshot: MarketSnapshotFrame,
    first_tick: Tick,
    timeframe: Any,
) -> int:
    """Send frames until the client leaves or the server closes. Returns the
    close code."""
    history = snapshot.history.candles
    builder = CandleBuilder(timeframe, history[-1] if history else None)
    builder.apply(first_tick)
    await websocket.send_json(wire(snapshot))

    last_state: FeedState = hub.state()
    await websocket.send_json(wire(MarketStatusFrame(state=last_state, sent_at=hub.now())))
    last_sent = time.monotonic()
    next_recheck = time.monotonic() + settings.market_stream_session_recheck_seconds

    receiver = asyncio.create_task(websocket.receive())
    overflow = asyncio.create_task(subscriber.overflowed.wait())
    getter: asyncio.Task[Tick] | None = None
    try:
        while True:
            getter = getter or asyncio.create_task(subscriber.queue.get())
            done, _ = await asyncio.wait(
                {receiver, overflow, getter}, timeout=1.0, return_when=asyncio.FIRST_COMPLETED
            )
            if receiver in done:
                message = receiver.result()
                if message["type"] == "websocket.disconnect":
                    return int(message.get("code", 1000))
                # The browser sends no application messages.
                await websocket.close(code=CLOSE_POLICY)
                return CLOSE_POLICY
            if overflow in done:
                await websocket.close(code=CLOSE_OVERLOADED)
                return CLOSE_OVERLOADED

            ticks: list[Tick] = []
            if getter in done:
                ticks.append(getter.result())
                getter = None
                while not subscriber.queue.empty():
                    ticks.append(subscriber.queue.get_nowait())
                # The snapshot's own tick may also be queued; it is not news.
                ticks = [tick for tick in ticks if tick != first_tick]
            if ticks and await _send_updates(websocket, builder, timeframe, ticks):
                last_sent = time.monotonic()

            state = hub.state()
            now = time.monotonic()
            if state != last_state or now - last_sent >= settings.market_stream_heartbeat_seconds:
                await websocket.send_json(wire(MarketStatusFrame(state=state, sent_at=hub.now())))
                last_state, last_sent = state, now

            if now >= next_recheck:
                next_recheck = now + settings.market_stream_session_recheck_seconds
                try:
                    session = await auth.resolve_session(token)
                except Exception as exc:
                    # Cannot confirm the session: close, and let the client
                    # retry with backoff (the next upgrade checks it again).
                    logger.warning(
                        "market_stream_session_check_failed", error_type=type(exc).__name__
                    )
                    await websocket.close(code=CLOSE_OVERLOADED)
                    return CLOSE_OVERLOADED
                if session is None:
                    await websocket.close(code=CLOSE_SESSION_ENDED)
                    return CLOSE_SESSION_ENDED
                if not settings.market_stream_enabled or not _eligible(settings, session):
                    await websocket.close(code=CLOSE_FORBIDDEN)
                    return CLOSE_FORBIDDEN
    finally:
        for task in (receiver, overflow, getter):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task


async def _send_updates(
    websocket: WebSocket, builder: CandleBuilder, timeframe: Any, ticks: list[Tick]
) -> bool:
    """Apply queued ticks and send the latest quote and candle. When the
    ticks cross into a new bar, the finished bar is sent first so the
    client keeps its final close."""
    pending: tuple[Tick, MarketCandle] | None = None
    sent = False
    for tick in ticks:
        candle = builder.apply(tick)
        if candle is None:
            continue
        if pending is not None and pending[1].time != candle.time:
            await _send_update(websocket, timeframe, *pending)
            sent = True
        pending = (tick, candle)
    if pending is not None:
        await _send_update(websocket, timeframe, *pending)
        sent = True
    return sent


async def _send_update(
    websocket: WebSocket, timeframe: Any, tick: Tick, candle: MarketCandle
) -> None:
    frame = MarketUpdateFrame(
        timeframe=timeframe, as_of=tick.exchange_time, quote=quote_from_tick(tick), candle=candle
    )
    await websocket.send_json(wire(frame))
