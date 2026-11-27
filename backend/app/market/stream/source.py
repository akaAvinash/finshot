"""Upstream tick sources: the protocol the hub drives, and the mock feed.

A source has one long-lived `run` loop that keeps an upstream connection
subscribed to the hub's wanted instruments and hands every tick to `emit`.
`run` returns or raises when the connection ends; the hub reconnects with
backoff. `history` returns recent candles for a snapshot."""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Protocol

from app.market.demo import _LISTINGS, _Listing
from app.market.schemas import MarketCandle, Timeframe
from app.market.stream.ticks import (
    INTERVAL_MINUTES,
    IST,
    SESSION_MINUTES,
    Tick,
    bucket_start,
    session_day,
    session_open,
)

Clock = Callable[[], datetime]

# How many sessions of history a snapshot carries, per timeframe. The same
# depth as the demo candles route.
HISTORY_SESSIONS: dict[Timeframe, int] = {
    "1m": 1,
    "5m": 1,
    "15m": 3,
    "30m": 5,
    "1h": 9,
    "1D": 38,
}


class SourceUnavailableError(Exception):
    """The upstream cannot serve data right now (auth, network, limits)."""


class Subscriptions:
    """The instruments the hub wants. A source watches `changed` to add or
    drop instruments on a live connection."""

    def __init__(self) -> None:
        self.ids: set[str] = set()
        self.changed = asyncio.Event()

    def set(self, ids: set[str]) -> None:
        if ids != self.ids:
            self.ids = set(ids)
            self.changed.set()


class TickSource(Protocol):
    always_open: bool
    """True for a feed that ticks around the clock (the mock), so the hub
    never reports the market `closed` for it."""

    def instrument_ids(self) -> frozenset[str]:
        """The catalog instruments this source can stream."""
        ...

    async def history(self, instrument_id: str, timeframe: Timeframe) -> list[MarketCandle]:
        """Recent candles, oldest first, ending with the current bar."""
        ...

    async def run(
        self,
        wanted: Subscriptions,
        emit: Callable[[Tick], None],
        heartbeat: Callable[[], None],
    ) -> None:
        """Stream until the connection ends. Call `heartbeat` on every upstream
        message, so the hub can tell a quiet feed from a dead one."""
        ...


def _round_tick(price: float, tick_size: float = 0.05) -> float:
    return round(round(price / tick_size) * tick_size, 2)


class MockTickSource:
    """MOCK prices, not real ones. A random walk from the demo catalog's last
    closes, ticking for every subscribed instrument around the clock. It
    exists so the stream and the chart can be built and tested without
    broker credentials. Refused in production by the settings."""

    always_open = True

    def __init__(self, clock: Clock, tick_seconds: float = 1.0, seed: int | None = None) -> None:
        self._clock = clock
        self._tick_seconds = tick_seconds
        self._random = random.Random(seed)  # noqa: S311 - mock prices, not security
        self._listings: dict[str, _Listing] = {listing.id: listing for listing in _LISTINGS}
        self._state: dict[str, Tick] = {}

    def instrument_ids(self) -> frozenset[str]:
        return frozenset(self._listings)

    def _current(self, instrument_id: str) -> Tick:
        tick = self._state.get(instrument_id)
        if tick is None:
            listing = self._listings[instrument_id]
            price = listing.close
            tick = Tick(
                instrument_id=instrument_id,
                price=price,
                open=listing.previous_close,
                high=max(price, listing.previous_close),
                low=min(price, listing.previous_close),
                previous_close=listing.previous_close,
                volume=listing.volume,
                exchange_time=self._clock(),
            )
            self._state[instrument_id] = tick
        return tick

    def _step(self, instrument_id: str) -> Tick:
        last = self._current(instrument_id)
        listing = self._listings[instrument_id]
        size = 0.01 if listing.is_index else 0.05
        price = max(_round_tick(last.price * (1 + self._random.gauss(0, 0.0004)), size), size)
        volume = None if last.volume is None else last.volume + self._random.randint(0, 2_000)
        tick = Tick(
            instrument_id=instrument_id,
            price=price,
            open=last.open,
            high=max(last.high, price),
            low=min(last.low, price),
            previous_close=last.previous_close,
            volume=volume,
            exchange_time=self._clock(),
        )
        self._state[instrument_id] = tick
        return tick

    async def history(self, instrument_id: str, timeframe: Timeframe) -> list[MarketCandle]:
        """Synthetic bars that end at the current bar with the current price.
        Walks backwards from the latest price, so a chart joins its live
        updates without a jump."""
        if instrument_id not in self._listings:
            raise SourceUnavailableError("unknown instrument")
        latest = self._current(instrument_id)
        now = self._clock()
        rng = random.Random(f"{instrument_id}:{timeframe}")  # noqa: S311 - mock data
        starts = _bar_starts(now, timeframe)
        candles: list[MarketCandle] = []
        close = latest.price
        index_like = latest.volume is None
        for start in reversed(starts):
            move = rng.gauss(0, 0.0015 * math.sqrt(INTERVAL_MINUTES[timeframe]))
            opening = max(_round_tick(close / (1 + move)), 0.05)
            wick = abs(rng.gauss(0, 0.0006)) * close
            candles.append(
                MarketCandle(
                    time=start,
                    open=opening,
                    high=_round_tick(max(opening, close) + wick),
                    low=max(_round_tick(min(opening, close) - wick), 0.0),
                    close=close,
                    volume=None if index_like else rng.randint(1_000, 50_000),
                )
            )
            close = opening
        candles.reverse()
        return candles

    async def run(
        self,
        wanted: Subscriptions,
        emit: Callable[[Tick], None],
        heartbeat: Callable[[], None],
    ) -> None:
        while True:
            heartbeat()
            for instrument_id in sorted(wanted.ids & set(self._listings)):
                emit(self._step(instrument_id))
            await asyncio.sleep(self._tick_seconds)


def _bar_starts(now: datetime, timeframe: Timeframe) -> Sequence[datetime]:
    """Bar opening instants for the last HISTORY_SESSIONS weekday sessions,
    oldest first, ending with the bar that contains `now` (or the last bar
    of the latest session when `now` is outside it)."""
    current = bucket_start(now, timeframe)
    sessions: list[datetime] = []
    cursor = session_open(session_day(current))
    while len(sessions) < HISTORY_SESSIONS[timeframe]:
        if cursor.astimezone(IST).weekday() < 5:
            sessions.append(cursor)
        cursor -= timedelta(days=1)
    sessions.reverse()
    if timeframe == "1D":
        return sessions
    interval = INTERVAL_MINUTES[timeframe]
    starts: list[datetime] = []
    for opens in sessions:
        for minute in range(0, SESSION_MINUTES, interval):
            start = opens + timedelta(minutes=minute)
            if start > current:
                break
            starts.append(start)
    return starts
