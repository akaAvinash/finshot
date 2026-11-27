"""Ticks, the NSE session clock, quotes and per-connection candle building.

All times are UTC on the wire. NSE is on IST (UTC+05:30, no daylight saving),
so a fixed offset is exact and needs no tz database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Literal

from app.market.schemas import InstrumentQuote, MarketCandle, Timeframe

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_OPEN_IST = timedelta(hours=9, minutes=15)
SESSION_CLOSE_IST = timedelta(hours=15, minutes=30)
# Ticks arrive from the 09:00 pre-open; the feed counts as open from then.
PREOPEN_IST = timedelta(hours=9)
SESSION_MINUTES = 375

INTERVAL_MINUTES: dict[Timeframe, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "1D": SESSION_MINUTES,
}

FeedState = Literal["live", "closed", "stale", "unavailable"]


@dataclass(frozen=True)
class Tick:
    """One upstream quote for one instrument. `volume` is the cumulative
    traded volume for the day (None for an index). `exchange_time` is the
    exchange timestamp of the quote, in UTC."""

    instrument_id: str
    price: float
    open: float
    high: float
    low: float
    previous_close: float
    volume: int | None
    exchange_time: datetime


def session_open(day: date) -> datetime:
    """09:15 IST on `day`, in UTC."""
    return datetime(day.year, day.month, day.day, tzinfo=IST).astimezone(UTC) + SESSION_OPEN_IST


def session_day(moment: datetime) -> date:
    return moment.astimezone(IST).date()


def market_hours(moment: datetime) -> bool:
    """True from the 09:00 pre-open to the 15:30 close on weekdays. Exchange
    holidays are not known here; on a holiday the feed reports `stale`
    during these hours because no ticks arrive."""
    local = moment.astimezone(IST)
    if local.weekday() >= 5:
        return False
    since_midnight = local - local.replace(hour=0, minute=0, second=0, microsecond=0)
    return PREOPEN_IST <= since_midnight < SESSION_CLOSE_IST


def bucket_start(moment: datetime, timeframe: Timeframe) -> datetime:
    """Opening instant of the candle that contains `moment`. Intraday bars
    are anchored to the 09:15 open, so the last bar of the day may be short.
    Pre-open ticks fall into the first bar and post-close ticks into the
    last, so every tick maps to a bar of its own session."""
    day = session_day(moment)
    opens = session_open(day)
    if timeframe == "1D":
        return opens
    interval = INTERVAL_MINUTES[timeframe]
    minutes = int((moment - opens).total_seconds() // 60)
    minutes = min(max(minutes, 0), SESSION_MINUTES - 1)
    return opens + timedelta(minutes=minutes - minutes % interval)


def _round2(value: float) -> float:
    return round(value + 0.0, 2)


def quote_from_tick(tick: Tick) -> InstrumentQuote:
    change = _round2(tick.price - tick.previous_close)
    percent = _round2(change / tick.previous_close * 100) if tick.previous_close > 0 else 0.0
    # A tick can report a day open of 0 before the first trade; fall back to
    # the price, and widen high/low so the quote stays self-consistent.
    opening = tick.open if tick.open > 0 else tick.price
    return InstrumentQuote(
        instrument_id=tick.instrument_id,
        price=tick.price,
        previous_close=tick.previous_close,
        change=change,
        change_percent=percent,
        open=opening,
        high=max(tick.high, opening, tick.price),
        low=min(tick.low if tick.low > 0 else tick.price, opening, tick.price),
        volume=tick.volume,
        trend="up" if change > 0 else "down" if change < 0 else "flat",
    )


class CandleBuilder:
    """Builds the latest candle for one connection's timeframe from ticks.

    Daily bars come straight from the tick's day open/high/low and cumulative
    volume. Intraday bars start from the last history candle when it is the
    current bar, so a connection opened mid-bar keeps the bar's real open,
    high, low and volume; after that, a bar's volume is the growth in the
    day's cumulative volume since the bar began. A tick older than the last
    one applied is ignored."""

    def __init__(self, timeframe: Timeframe, last_history: MarketCandle | None) -> None:
        self.timeframe: Timeframe = timeframe
        self._candle: MarketCandle | None = last_history
        self._last_time: datetime | None = None
        self._last_volume: int | None = None
        self._volume_base: int | None = None
        self._seeded = last_history is not None

    def apply(self, tick: Tick) -> MarketCandle | None:
        if self._last_time is not None and tick.exchange_time < self._last_time:
            return None
        first_tick = self._last_time is None
        self._last_time = tick.exchange_time
        start = bucket_start(tick.exchange_time, self.timeframe)
        if self.timeframe == "1D":
            quote = quote_from_tick(tick)
            self._candle = MarketCandle(
                time=start,
                open=quote.open,
                high=quote.high,
                low=quote.low,
                close=tick.price,
                volume=tick.volume,
            )
            return self._candle

        current = self._candle
        if current is not None and current.time > start:
            return None  # the history already has a later bar than this tick
        if current is not None and current.time == start:
            if first_tick and self._seeded and tick.volume is not None:
                self._volume_base = tick.volume - (current.volume or 0)
            candle = MarketCandle(
                time=start,
                open=current.open,
                high=max(current.high, tick.price),
                low=min(current.low, tick.price),
                close=tick.price,
                volume=self._bar_volume(tick),
            )
        else:
            # A new bar: its volume counts from the last cumulative value
            # seen before it, or from this tick when there is none.
            if tick.volume is not None:
                self._volume_base = (
                    self._last_volume if self._last_volume is not None else tick.volume
                )
            candle = MarketCandle(
                time=start,
                open=tick.price,
                high=tick.price,
                low=tick.price,
                close=tick.price,
                volume=self._bar_volume(tick),
            )
        if tick.volume is not None:
            self._last_volume = tick.volume
        self._candle = candle
        return candle

    def _bar_volume(self, tick: Tick) -> int | None:
        if tick.volume is None:
            return None
        base = self._volume_base if self._volume_base is not None else tick.volume
        # The day's volume never falls; guard against a feed that restarts it.
        return max(tick.volume - base, 0)
