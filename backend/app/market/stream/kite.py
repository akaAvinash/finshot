"""Zerodha Kite Connect market data source (read-only).

Uses the Kite ticker WebSocket for quotes and the historical candles API for
snapshots. It never calls an order endpoint, and order messages that arrive
on the ticker connection are dropped. Candles are kept in memory only.

Credentials come from the server environment: KITE_API_KEY, and the daily
access token in the file named by KITE_ACCESS_TOKEN_FILE. The file is read
again on every connection attempt, so a new token takes effect without a
restart (see `python -m app.market.stream.kite_session`). Neither value is
ever logged: errors are logged by type or HTTP status only.

The binary packet layout follows https://kite.trade/docs/connect/v3/websocket/
(big-endian, prices in paise for NSE). It has been tested against recorded
layouts only; the first live connection is the owner's check."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog
from pydantic import SecretStr, ValidationError
from websockets.asyncio.client import connect

from app.market.schemas import MarketCandle, Timeframe
from app.market.stream.source import HISTORY_SESSIONS, SourceUnavailableError, Subscriptions
from app.market.stream.ticks import IST, Tick, session_day, session_open

logger = structlog.get_logger(__name__)

API_ROOT = "https://api.kite.trade"
TICKER_URL = "wss://ws.kite.trade"

# Catalog instrument -> Kite NSE tradingsymbol. Instrument tokens are looked
# up from Kite's instrument list once a day, never hard-coded.
KITE_SYMBOLS: dict[str, str] = {
    "NSE:NIFTY50": "NIFTY 50",
    "NSE:BANKNIFTY": "NIFTY BANK",
    "NSE:FINNIFTY": "NIFTY FIN SERVICE",
    "NSE:INDIAVIX": "INDIA VIX",
    "NSE:RELIANCE": "RELIANCE",
    "NSE:HDFCBANK": "HDFCBANK",
    "NSE:SBIN": "SBIN",
    "NSE:TCS": "TCS",
    "NSE:INFY": "INFY",
    "NSE:ICICIBANK": "ICICIBANK",
    "NSE:BHARTIARTL": "BHARTIARTL",
    "NSE:ITC": "ITC",
}

_INTERVALS: dict[Timeframe, str] = {
    "1m": "minute",
    "5m": "5minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "1D": "day",
}

_SEGMENT_CDS = 3
_SEGMENT_BCD = 6
_SEGMENT_INDICES = 9


@dataclass(frozen=True)
class RawTick:
    token: int
    price: float
    open: float
    high: float
    low: float
    previous_close: float
    volume: int | None
    exchange_time: datetime | None


def _u32(packet: bytes, start: int) -> int:
    value: int = struct.unpack(">I", packet[start : start + 4])[0]
    return value


def _divisor(token: int) -> float:
    segment = token & 0xFF
    if segment == _SEGMENT_CDS:
        return 10_000_000.0
    if segment == _SEGMENT_BCD:
        return 10_000.0
    return 100.0


def _epoch(seconds: int) -> datetime | None:
    return datetime.fromtimestamp(seconds, UTC) if seconds > 0 else None


def parse_ticker_frame(data: bytes) -> list[RawTick]:
    """Split one binary ticker frame into ticks. A 1-byte frame is a
    heartbeat and yields nothing; LTP-only packets (8 bytes) are skipped
    because they carry no OHLC. Malformed frames yield nothing."""
    if len(data) < 2:
        return []
    count = struct.unpack(">H", data[0:2])[0]
    ticks: list[RawTick] = []
    offset = 2
    for _ in range(count):
        if offset + 2 > len(data):
            break
        length = struct.unpack(">H", data[offset : offset + 2])[0]
        packet = data[offset + 2 : offset + 2 + length]
        offset += 2 + length
        if len(packet) != length:
            break
        tick = _parse_packet(packet)
        if tick is not None:
            ticks.append(tick)
    return ticks


def _parse_packet(packet: bytes) -> RawTick | None:
    length = len(packet)
    if length < 8:
        return None
    token = _u32(packet, 0)
    div = _divisor(token)
    if length in (28, 32) and token & 0xFF == _SEGMENT_INDICES:
        return RawTick(
            token=token,
            price=_u32(packet, 4) / div,
            high=_u32(packet, 8) / div,
            low=_u32(packet, 12) / div,
            open=_u32(packet, 16) / div,
            previous_close=_u32(packet, 20) / div,
            volume=None,
            exchange_time=_epoch(_u32(packet, 28)) if length == 32 else None,
        )
    if length in (44, 184):
        return RawTick(
            token=token,
            price=_u32(packet, 4) / div,
            volume=_u32(packet, 16),
            open=_u32(packet, 28) / div,
            high=_u32(packet, 32) / div,
            low=_u32(packet, 36) / div,
            previous_close=_u32(packet, 40) / div,
            exchange_time=_epoch(_u32(packet, 60)) if length == 184 else None,
        )
    return None


def _parse_candle_time(value: str, timeframe: Timeframe) -> datetime:
    moment = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").astimezone(UTC)
    if timeframe == "1D":
        # Kite dates daily bars at midnight IST; a daily bar here opens at
        # the session open, like the demo candles.
        return session_open(session_day(moment))
    return moment


def parse_history(payload: Any, timeframe: Timeframe) -> list[MarketCandle]:
    """Kite historical candles to MarketCandle, oldest first. Rows that are
    malformed or fail the candle invariants are dropped."""
    rows = payload.get("data", {}).get("candles", []) if isinstance(payload, dict) else []
    candles: dict[datetime, MarketCandle] = {}
    for row in rows:
        try:
            stamp, opening, high, low, close, volume = row[:6]
            moment = _parse_candle_time(str(stamp), timeframe)
            candles[moment] = MarketCandle(
                time=moment,
                open=float(opening),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=int(volume),
            )
        except (ValueError, TypeError, ValidationError):
            continue
    return [candles[key] for key in sorted(candles)]


def _keep_sessions(candles: list[MarketCandle], sessions: int) -> list[MarketCandle]:
    days = sorted({session_day(candle.time) for candle in candles})[-sessions:]
    keep = set(days)
    return [candle for candle in candles if session_day(candle.time) in keep]


class KiteTickSource:
    always_open = False

    def __init__(
        self,
        *,
        api_key: SecretStr,
        access_token_file: str,
        clock: Callable[[], datetime],
        http: httpx.AsyncClient | None = None,
        history_cache_seconds: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._token_file = Path(access_token_file)
        self._clock = clock
        self._http = http or httpx.AsyncClient(timeout=10.0)
        self._tokens: dict[str, int] = {}
        self._ids_by_token: dict[int, str] = {}
        self._tokens_day: date | None = None
        self._index_ids = {"NSE:NIFTY50", "NSE:BANKNIFTY", "NSE:FINNIFTY", "NSE:INDIAVIX"}
        self._history_cache: dict[tuple[str, Timeframe], tuple[float, list[MarketCandle]]] = {}
        self._cache_seconds = history_cache_seconds
        self._pace = asyncio.Lock()
        self._last_call = 0.0

    def instrument_ids(self) -> frozenset[str]:
        return frozenset(KITE_SYMBOLS)

    # ----------------------------------------------------------- credentials

    def _access_token(self) -> str:
        try:
            token = self._token_file.read_text().strip()
        except OSError as exc:
            raise SourceUnavailableError("access token file unreadable") from exc
        if not token:
            raise SourceUnavailableError("access token file empty")
        return token

    def _headers(self) -> dict[str, str]:
        key = self._api_key.get_secret_value()
        return {"X-Kite-Version": "3", "Authorization": f"token {key}:{self._access_token()}"}

    async def _get(self, path: str, params: dict[str, str] | None = None) -> httpx.Response:
        # Kite allows 3 historical requests a second; keep to about that for
        # every REST call this source makes.
        async with self._pace:
            wait = self._last_call + 0.35 - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
            try:
                response = await self._http.get(
                    f"{API_ROOT}{path}", params=params, headers=self._headers()
                )
            except httpx.HTTPError as exc:
                raise SourceUnavailableError(type(exc).__name__) from exc
        if response.status_code != 200:
            logger.warning("kite_http_error", status=response.status_code, path=path.split("/")[1])
            raise SourceUnavailableError(f"kite http {response.status_code}")
        return response

    # ---------------------------------------------------------- instruments

    async def _resolve_tokens(self) -> None:
        today = session_day(self._clock())
        if self._tokens_day == today and self._tokens:
            return
        response = await self._get("/instruments/NSE")
        wanted = {symbol: instrument_id for instrument_id, symbol in KITE_SYMBOLS.items()}
        tokens: dict[str, int] = {}
        for row in csv.DictReader(io.StringIO(response.text)):
            instrument_id = wanted.get(row.get("tradingsymbol", ""))
            if instrument_id is None or row.get("exchange") != "NSE":
                continue
            is_index = row.get("segment") == "INDICES"
            if is_index != (instrument_id in self._index_ids):
                continue
            try:
                tokens[instrument_id] = int(row["instrument_token"])
            except (KeyError, ValueError):
                continue
        missing = sorted(set(KITE_SYMBOLS) - set(tokens))
        if missing:
            logger.warning("kite_instruments_missing", instruments=missing)
        if not tokens:
            raise SourceUnavailableError("no instruments resolved")
        self._tokens = tokens
        self._ids_by_token = {token: instrument_id for instrument_id, token in tokens.items()}
        self._tokens_day = today

    # --------------------------------------------------------------- history

    async def history(self, instrument_id: str, timeframe: Timeframe) -> list[MarketCandle]:
        key = (instrument_id, timeframe)
        cached = self._history_cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < self._cache_seconds:
            return cached[1]
        await self._resolve_tokens()
        token = self._tokens.get(instrument_id)
        if token is None:
            raise SourceUnavailableError("instrument not resolved")
        sessions = HISTORY_SESSIONS[timeframe]
        now = self._clock().astimezone(IST)
        # Calendar days that surely hold `sessions` trading days, holidays included.
        start = now - timedelta(days=sessions * 7 // 5 + 7)
        response = await self._get(
            f"/instruments/historical/{token}/{_INTERVALS[timeframe]}",
            params={
                "from": start.strftime("%Y-%m-%d %H:%M:%S"),
                "to": now.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceUnavailableError("invalid history payload") from exc
        candles = _keep_sessions(parse_history(payload, timeframe), sessions)
        if instrument_id in self._index_ids:
            candles = [candle.model_copy(update={"volume": None}) for candle in candles]
        self._history_cache[key] = (time.monotonic(), candles)
        return candles

    # ---------------------------------------------------------------- ticker

    def _to_tick(self, raw: RawTick) -> Tick | None:
        instrument_id = self._ids_by_token.get(raw.token)
        if instrument_id is None or raw.price <= 0:
            return None
        return Tick(
            instrument_id=instrument_id,
            price=raw.price,
            open=raw.open,
            high=raw.high,
            low=raw.low,
            previous_close=raw.previous_close,
            volume=raw.volume,
            exchange_time=raw.exchange_time or self._clock(),
        )

    async def run(
        self,
        wanted: Subscriptions,
        emit: Callable[[Tick], None],
        heartbeat: Callable[[], None],
    ) -> None:
        await self._resolve_tokens()
        key = self._api_key.get_secret_value()
        url = f"{TICKER_URL}?api_key={key}&access_token={self._access_token()}"
        async with connect(url, open_timeout=10, max_size=2**20) as ws:
            subscribed: set[int] = set()

            async def sync() -> None:
                nonlocal subscribed
                while True:
                    wanted.changed.clear()
                    target = {self._tokens[i] for i in wanted.ids if i in self._tokens}
                    added, removed = sorted(target - subscribed), sorted(subscribed - target)
                    if removed:
                        await ws.send(json.dumps({"a": "unsubscribe", "v": removed}))
                    if added:
                        await ws.send(json.dumps({"a": "subscribe", "v": added}))
                        await ws.send(json.dumps({"a": "mode", "v": ["full", added]}))
                    subscribed = target
                    await wanted.changed.wait()

            syncer = asyncio.create_task(sync())
            try:
                async for message in ws:
                    if syncer.done():
                        syncer.result()  # surface a send failure
                    heartbeat()
                    if isinstance(message, str):
                        self._text_message(message)
                        continue
                    for raw in parse_ticker_frame(message):
                        tick = self._to_tick(raw)
                        if tick is not None:
                            emit(tick)
            finally:
                syncer.cancel()

    @staticmethod
    def _text_message(message: str) -> None:
        """Order updates are dropped: the market feed never acts on orders.
        Errors are logged by type only."""
        try:
            kind = json.loads(message).get("type")
        except (ValueError, AttributeError):
            return
        if kind == "error":
            logger.warning("kite_ticker_error")

    async def aclose(self) -> None:
        await self._http.aclose()
