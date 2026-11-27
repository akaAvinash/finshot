"""/api/v1/market/stream: the owner-only, read-only market WebSocket, as
specified in contracts/live-market-stream.asyncapi.yaml.

Before the upgrade, checks run in this order and fail with an HTTP response
in the shared error shape: 404 when the stream is disabled, 403 for an Origin
other than PUBLIC_ORIGIN, 401 for a missing, expired or revoked session, 403
for any account other than the configured owner (tester sessions and
sessions pending authenticator setup included), 400 for invalid selection
parameters, 503 when the feed cannot serve a snapshot or the connection cap
is reached, or the session cannot be checked (database down).

The session is checked once more after the snapshot is prepared and before
the upgrade, so no market data leaves for a session that ended meanwhile.

After the upgrade the server sends a snapshot, then updates and status
frames. The session is checked again every
MARKET_STREAM_SESSION_RECHECK_SECONDS, before anything else is sent, and a
passing check renews it (owner decision: an open chart keeps the session
alive until its absolute expiry). A check never renews a session it refuses.
Closes: 4401 session ended, 4403 account no longer eligible, 1013 for a
client that falls behind, a send that stalls past
MARKET_STREAM_SEND_TIMEOUT_SECONDS or a check that cannot reach the
database, 1008 for a client that sends any message."""

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


async def _authorize(websocket: WebSocket, settings: Settings, auth: AuthService) -> str:
    if websocket.headers.get("origin") != settings.public_origin:
        raise _Denied(403, "ORIGIN_NOT_ALLOWED", "This origin may not open the market stream.")
    token = websocket.cookies.get(SESSION_COOKIE)
    if token is None:
        raise _Denied(401, "UNAUTHENTICATED", "Sign in to continue.")
    # No renewal yet: the selection may still refuse the upgrade.
    code = await _check_session(auth, settings, token, renew=False)
    if code is not None:
        raise _UPGRADE_DENIALS[code]()
    return token


async def _check_session(
    auth: AuthService, settings: Settings, token: str, *, renew: bool = True
) -> int | None:
    """None when the session is valid and eligible (and then, with `renew`,
    renews it: an open stream keeps the session alive). Otherwise the close
    code: 4401 session ended, 4403 not eligible, 1013 the check itself
    failed. Checks without renewing first, so a refused session is never
    extended."""
    try:
        session = await auth.resolve_session(token, renew=False)
        if session is None:
            return CLOSE_SESSION_ENDED
        if not settings.market_stream_enabled or not _eligible(settings, session):
            return CLOSE_FORBIDDEN
        if renew and await auth.resolve_session(token) is None:
            return CLOSE_SESSION_ENDED  # ended between the two reads
    except Exception as exc:  # database or cache down: fail closed
        logger.warning("market_stream_session_check_failed", error_type=type(exc).__name__)
        return CLOSE_OVERLOADED
    return None


_UPGRADE_DENIALS: dict[int, Any] = {
    CLOSE_SESSION_ENDED: lambda: _Denied(401, "UNAUTHENTICATED", "Sign in to continue."),
    CLOSE_FORBIDDEN: lambda: _Denied(
        403, "MARKET_STREAM_FORBIDDEN", "This account may not open the market stream."
    ),
    CLOSE_OVERLOADED: lambda: _unavailable(),
}


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
        token = await _authorize(websocket, settings, auth)
        instrument_id, timeframe = _selection(websocket, hub)
    except _Denied as denied:
        await _deny(websocket, denied)
        return

    async with hub.subscribe(instrument_id) as subscriber:
        try:
            if hub.connection_count > settings.market_stream_max_connections:
                raise _unavailable()
            frame, tick = await _snapshot(hub, settings, instrument_id, timeframe)
            # Preparing the snapshot can take seconds: check the session again
            # right before any market data leaves the server. Every check from
            # here on renews, since the upgrade is now accepted.
            code = await _check_session(auth, settings, token)
            checked_at = time.monotonic()
            if code is not None:
                raise _UPGRADE_DENIALS[code]()
        except _Denied as denied:
            await _deny(websocket, denied)
            return
        await websocket.accept()
        logger.info("market_stream_opened", instrument_id=instrument_id, timeframe=timeframe)
        code = CLOSE_NORMAL
        try:
            code = await _serve(
                websocket,
                hub,
                subscriber,
                settings,
                auth,
                token,
                frame,
                tick,
                timeframe,
                checked_at,
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
    checked_at: float,
) -> int:
    """Send frames until the client leaves or the server closes. Returns the
    close code.

    Frames go through a bounded outbox to a separate writer task, so a client
    that stops reading never holds up the session check, the overflow check
    or a disconnect: the control loop below never waits on a send. The writer
    gives each send MARKET_STREAM_SEND_TIMEOUT_SECONDS; a stalled send, or an
    outbox that fills, ends the stream with 1013."""
    deadline = settings.market_stream_send_timeout_seconds
    outbox: asyncio.Queue[Any] = asyncio.Queue(maxsize=settings.market_stream_queue_size)

    async def write() -> None:
        while True:
            frame = await outbox.get()
            async with asyncio.timeout(deadline):
                await websocket.send_json(wire(frame))

    writer = asyncio.create_task(write())
    receiver = asyncio.create_task(websocket.receive())
    overflow = asyncio.create_task(subscriber.overflowed.wait())
    getter: asyncio.Task[Tick] | None = None

    async def close(code: int) -> int:
        # Stop the writer first, so nothing else is sent, then try a close
        # frame within the same deadline (the client may not be reading).
        writer.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await writer
        with contextlib.suppress(TimeoutError, RuntimeError, OSError, WebSocketDisconnect):
            async with asyncio.timeout(deadline):
                await websocket.close(code=code)
        return code

    def enqueue(frame: Any) -> bool:
        try:
            outbox.put_nowait(frame)
        except asyncio.QueueFull:
            return False
        return True

    history = snapshot.history.candles
    builder = CandleBuilder(timeframe, history[-1] if history else None)
    builder.apply(first_tick)
    last_state: FeedState = hub.state()
    enqueue(snapshot)
    enqueue(MarketStatusFrame(state=last_state, sent_at=hub.now()))
    last_sent = time.monotonic()
    # Counted from the last check, not from when frames were sent.
    next_recheck = checked_at + settings.market_stream_session_recheck_seconds

    try:
        while True:
            getter = getter or asyncio.create_task(subscriber.queue.get())
            done, _ = await asyncio.wait(
                {receiver, overflow, getter, writer},
                timeout=1.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receiver in done:
                message = receiver.result()
                if message["type"] == "websocket.disconnect":
                    return int(message.get("code", 1000))
                # The browser sends no application messages.
                return await close(CLOSE_POLICY)
            if writer in done:
                error = writer.exception()
                if isinstance(error, TimeoutError):  # before OSError: it subclasses it
                    # A send stalled past the deadline: the client is not reading.
                    return await close(CLOSE_OVERLOADED)
                if isinstance(error, WebSocketDisconnect | OSError):
                    return 1006
                return await close(CLOSE_OVERLOADED)
            if overflow in done:
                return await close(CLOSE_OVERLOADED)

            # Session first: nothing more is queued once a due check fails.
            now = time.monotonic()
            if now >= next_recheck:
                code = await _check_session(auth, settings, token)
                next_recheck = time.monotonic() + settings.market_stream_session_recheck_seconds
                if code is not None:
                    return await close(code)

            ticks: list[Tick] = []
            if getter in done:
                ticks.append(getter.result())
                getter = None
                while not subscriber.queue.empty():
                    ticks.append(subscriber.queue.get_nowait())
                # The snapshot's own tick may also be queued; it is not news.
                ticks = [tick for tick in ticks if tick != first_tick]
            frames = _update_frames(builder, timeframe, ticks)
            if frames:
                if not all(enqueue(frame) for frame in frames):
                    return await close(CLOSE_OVERLOADED)
                last_sent = time.monotonic()

            state = hub.state()
            now = time.monotonic()
            if state != last_state or now - last_sent >= settings.market_stream_heartbeat_seconds:
                if not enqueue(MarketStatusFrame(state=state, sent_at=hub.now())):
                    return await close(CLOSE_OVERLOADED)
                last_state, last_sent = state, now
    finally:
        for task in (writer, receiver, overflow, getter):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task


def _update_frames(
    builder: CandleBuilder, timeframe: Any, ticks: list[Tick]
) -> list[MarketUpdateFrame]:
    """Apply queued ticks; one frame with the latest quote and candle. When
    the ticks cross into a new bar, the finished bar's frame comes first so
    the client keeps its final close."""
    frames: list[MarketUpdateFrame] = []
    pending: tuple[Tick, MarketCandle] | None = None
    for tick in ticks:
        candle = builder.apply(tick)
        if candle is None:
            continue
        if pending is not None and pending[1].time != candle.time:
            frames.append(_update_frame(timeframe, *pending))
        pending = (tick, candle)
    if pending is not None:
        frames.append(_update_frame(timeframe, *pending))
    return frames


def _update_frame(timeframe: Any, tick: Tick, candle: MarketCandle) -> MarketUpdateFrame:
    return MarketUpdateFrame(
        timeframe=timeframe, as_of=tick.exchange_time, quote=quote_from_tick(tick), candle=candle
    )
