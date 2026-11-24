"""DEMO market data. Not real prices.

A deterministic port of frontend/src/lib/api/market-fixture.ts: the same
twelve NSE instruments, IDs, aliases, closing prices, seeded random walk and
2026-11-23 snapshot, so the API and the frontend's demo client serve the same
numbers. Every response this provider builds carries `source: "demo"`.

Simplifications, inherited from the frontend fixture and fine for a demo:
the session calendar skips weekends but not NSE holidays, and the snapshot
date is fixed rather than following the clock."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from app.market.schemas import (
    TIMEFRAMES,
    Instrument,
    InstrumentQuote,
    MarketCandle,
    MarketCandles,
    MarketOverview,
    MarketSession,
    Timeframe,
)

DemoScenario = Literal["ready", "stale", "empty"]

SNAPSHOT_DATE = date(2026, 11, 23)
_OPEN_UTC = timedelta(hours=3, minutes=45)  # 09:15 IST
_CLOSE_UTC = timedelta(hours=10)  # 15:30 IST
_MINUTES_PER_SESSION = 375
_INTERVAL_MINUTES: dict[Timeframe, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "1D": _MINUTES_PER_SESSION,
}
# How many sessions of history each timeframe returns.
_SESSION_COUNTS: dict[Timeframe, int] = {"1m": 1, "5m": 1, "15m": 3, "30m": 5, "1h": 9, "1D": 38}
_MASK32 = 0xFFFFFFFF


@dataclass(frozen=True)
class _Listing:
    ticker: str
    name: str
    close: float
    previous_close: float
    symbol: str | None = None
    aliases: tuple[str, ...] = ()
    volume: int | None = None  # None marks a cash index (no traded volume)

    @property
    def id(self) -> str:
        return f"NSE:{self.ticker}"

    @property
    def is_index(self) -> bool:
        return self.volume is None


_LISTINGS: tuple[_Listing, ...] = (
    _Listing("NIFTY50", "Nifty 50 Index", 24481.10, 24349.61, "NIFTY 50", ("NIFTY",)),
    _Listing(
        "BANKNIFTY", "Nifty Bank Index", 52364.20, 52015.70, aliases=("BANK NIFTY", "NIFTY BANK")
    ),
    _Listing(
        "FINNIFTY",
        "Nifty Financial Services Index",
        24832.55,
        24735.80,
        aliases=("NIFTY FIN SERVICE",),
    ),
    _Listing("INDIAVIX", "India Volatility Index", 12.46, 12.87, "INDIA VIX"),
    _Listing("RELIANCE", "Reliance Industries", 1429.65, 1432.23, aliases=("RIL",), volume=8235640),
    _Listing("HDFCBANK", "HDFC Bank", 988.25, 984.12, aliases=("HDFC",), volume=12104783),
    _Listing("SBIN", "State Bank of India", 857.30, 854.22, aliases=("SBI",), volume=9812250),
    _Listing("TCS", "Tata Consultancy Services", 3124.50, 3096.94, volume=2648120),
    _Listing("INFY", "Infosys", 1546.35, 1551.16, volume=6123250),
    _Listing("ICICIBANK", "ICICI Bank", 1382.80, 1376.15, volume=7081460),
    _Listing("BHARTIARTL", "Bharti Airtel", 1738.75, 1745.55, aliases=("AIRTEL",), volume=4821160),
    _Listing("ITC", "ITC Limited", 412.30, 412.30, volume=7453125),
)


# --- Numeric helpers that reproduce JavaScript semantics exactly -----------


def _js_round(value: float) -> int:
    """Math.round: nearest integer, halves toward +infinity."""
    floor = math.floor(value)
    return floor + 1 if value - floor >= 0.5 else floor


def _round_price(value: float) -> float:
    return _js_round(value * 100) / 100


def _seeded_random(key: str) -> Callable[[], float]:
    """The fixture's 32-bit LCG, seeded from the key's characters."""
    state = 7
    for letter in key:
        state = (state * 31 + ord(letter)) & _MASK32

    def next_value() -> float:
        nonlocal state
        state = (state * 1664525 + 1013904223) & _MASK32
        return state / 4294967296

    return next_value


# --- Fixture generation -----------------------------------------------------


@dataclass(frozen=True)
class _Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None


def _date_for_session(session: int) -> date:
    """`session` trading days (Mon-Fri) before the snapshot date."""
    day = SNAPSHOT_DATE
    remaining = session
    while remaining > 0:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            remaining -= 1
    return day


def _at(day: date, offset: timedelta) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC) + offset


def _closing_price(listing: _Listing, session: int) -> float:
    if session == 0:
        return listing.close
    if session == 1:
        return listing.previous_close
    random = _seeded_random(f"{listing.id}:close:{session}")
    movement = -session * 0.00115 + math.sin(session * 0.63) * 0.008 + (random() - 0.5) * 0.011
    return _round_price(listing.previous_close * (1 + movement))


def _session_minutes(listing: _Listing, session: int) -> list[_Bar]:
    """One-minute bars for one session. The order of random() calls matches
    the frontend fixture exactly; changing it changes every number."""
    day = _date_for_session(session)
    start = _at(day, _OPEN_UTC)
    random = _seeded_random(f"{listing.id}:{day.isoformat()}")
    previous_close = _closing_price(listing, session + 1)
    close = _closing_price(listing, session)
    amplitude = close * (0.0033 if listing.is_index else 0.0043)
    phase = random() * math.pi
    opening = _round_price(previous_close * (1 + (random() - 0.5) * 0.003))
    total_volume: int | None
    if listing.volume is None:
        total_volume = None
    elif session == 0:
        total_volume = listing.volume
    else:
        total_volume = _js_round(listing.volume * (0.7 + random() * 0.57))

    weights: list[float] = []
    weight_total = 0.0
    for minute in range(_MINUTES_PER_SESSION):
        progress = minute / (_MINUTES_PER_SESSION - 1)
        weight = 0.54 + (progress - 0.49) ** 2 * 3.6 + random() * 0.45
        weight_total += weight
        weights.append(weight)

    bars: list[_Bar] = []
    remaining_volume = total_volume
    bar_open = opening
    drift = 0.0
    last = _MINUTES_PER_SESSION - 1
    for minute, weight in enumerate(weights):
        progress = (minute + 1) / _MINUTES_PER_SESSION
        envelope = math.sin(progress * math.pi)
        drift = drift * 0.9 + (random() - 0.5) * 0.21
        wave = (
            math.sin(progress * 13 + phase) * 0.52 + math.cos(progress * 26 + phase) * 0.25 + drift
        )
        bar_close = (
            close
            if minute == last
            else _round_price(opening + (close - opening) * progress + amplitude * envelope * wave)
        )
        wick = close * 0.00038
        high = _round_price(max(bar_open, bar_close) + random() * wick)
        low = _round_price(min(bar_open, bar_close) - random() * wick)
        volume: int | None = None
        if total_volume is not None and remaining_volume is not None:
            volume = (
                remaining_volume
                if minute == last
                else math.floor(total_volume * weight / weight_total)
            )
            remaining_volume -= volume
        bars.append(_Bar(start + timedelta(minutes=minute), bar_open, high, low, bar_close, volume))
        bar_open = bar_close
    return bars


def _aggregate(bars: Sequence[_Bar], interval: int) -> list[_Bar]:
    """Group one-minute bars from the session open. The last group may be
    shorter (for example 375 minutes in 30-minute bars ends with 15)."""
    out: list[_Bar] = []
    for start in range(0, len(bars), interval):
        chunk = bars[start : start + interval]
        first = chunk[0]
        volume = None if first.volume is None else sum(bar.volume or 0 for bar in chunk)
        out.append(
            _Bar(
                time=first.time,
                open=first.open,
                high=max(bar.high for bar in chunk),
                low=min(bar.low for bar in chunk),
                close=chunk[-1].close,
                volume=volume,
            )
        )
    return out


def snapshot_time(stale: bool = False) -> datetime:
    """Close of the snapshot session (or of the session before, when stale)."""
    return _at(_date_for_session(1 if stale else 0), _CLOSE_UTC)


def _history(listing: _Listing, timeframe: Timeframe, stale: bool) -> list[MarketCandle]:
    offset = 1 if stale else 0
    count = _SESSION_COUNTS[timeframe]
    interval = _INTERVAL_MINUTES[timeframe]
    candles: list[MarketCandle] = []
    for index in range(count):  # oldest session first
        session = count - 1 - index + offset
        for bar in _aggregate(_session_minutes(listing, session), interval):
            candles.append(
                MarketCandle(
                    time=bar.time,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
            )
    return candles


def _quote(listing: _Listing) -> InstrumentQuote:
    (day,) = _aggregate(_session_minutes(listing, 0), _MINUTES_PER_SESSION)
    change = _round_price(day.close - listing.previous_close)
    return InstrumentQuote(
        instrument_id=listing.id,
        price=day.close,
        previous_close=listing.previous_close,
        change=change,
        change_percent=_round_price(change / listing.previous_close * 100),
        open=day.open,
        high=day.high,
        low=day.low,
        volume=day.volume,
        trend="up" if change > 0 else "down" if change < 0 else "flat",
    )


class DemoMarketDataProvider:
    """Deterministic demo data. `scenario` mirrors the frontend mock:
    "ready" (latest snapshot), "stale" (previous session, freshness=stale),
    "empty" (known instruments, no candle history)."""

    def __init__(self, scenario: DemoScenario = "ready") -> None:
        self.scenario: DemoScenario = scenario
        self._listings = {listing.id: listing for listing in _LISTINGS}
        self._instruments = tuple(
            Instrument(
                id=listing.id,
                symbol=listing.symbol or listing.ticker,
                name=listing.name,
                kind="index" if listing.is_index else "equity",
                aliases=listing.aliases,
            )
            for listing in _LISTINGS
        )
        self._candles: dict[tuple[str, Timeframe], MarketCandles] = {}
        self._overview: MarketOverview | None = None

    async def list_instruments(self) -> Sequence[Instrument]:
        return self._instruments

    async def get_overview(self) -> MarketOverview:
        if self._overview is None:
            self._overview = await asyncio.to_thread(self._build_overview)
        return self._overview

    def _build_overview(self) -> MarketOverview:
        return MarketOverview(
            source="demo",
            as_of=snapshot_time(),
            session=MarketSession(
                status="closed",
                opens_at=_at(SNAPSHOT_DATE, _OPEN_UTC),
                closes_at=_at(SNAPSHOT_DATE, _CLOSE_UTC),
            ),
            quotes=[_quote(listing) for listing in _LISTINGS],
        )

    async def get_candles(self, instrument_id: str, timeframe: Timeframe) -> MarketCandles | None:
        listing = self._listings.get(instrument_id)
        if listing is None:
            return None
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"unsupported timeframe {timeframe!r}")
        key = (instrument_id, timeframe)
        cached = self._candles.get(key)
        if cached is None:
            # Generating a long history takes tens of milliseconds; keep it
            # off the event loop. Results are cached, so this runs once per key.
            cached = await asyncio.to_thread(self._build_candles, listing, timeframe)
            self._candles[key] = cached
        return cached

    def _build_candles(self, listing: _Listing, timeframe: Timeframe) -> MarketCandles:
        stale = self.scenario == "stale"
        return MarketCandles(
            instrument_id=listing.id,
            timeframe=timeframe,
            source="demo",
            as_of=snapshot_time(stale),
            freshness="stale" if stale else "fresh",
            candles=[] if self.scenario == "empty" else _history(listing, timeframe, stale),
        )
