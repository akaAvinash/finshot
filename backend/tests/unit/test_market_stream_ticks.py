"""Session clock, quotes and candle building for the owner market stream."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.market.schemas import MarketCandle
from app.market.stream.ticks import (
    CandleBuilder,
    Tick,
    bucket_start,
    market_hours,
    quote_from_tick,
    session_open,
)

# 2026-11-27 is a Friday. 09:15 IST = 03:45 UTC, 15:30 IST = 10:00 UTC.
OPEN = datetime(2026, 11, 27, 3, 45, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return OPEN + timedelta(minutes=minutes)


def tick(minutes: float, price: float, volume: int | None = 1000, **kw: float) -> Tick:
    return Tick(
        instrument_id="NSE:RELIANCE",
        price=price,
        open=kw.get("open", 100.0),
        high=kw.get("high", max(price, 100.0)),
        low=kw.get("low", min(price, 100.0)),
        previous_close=kw.get("previous_close", 99.0),
        volume=volume,
        exchange_time=at(minutes),
    )


def test_session_open_is_0915_ist() -> None:
    assert session_open(OPEN.date()) == OPEN


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 11, 27, 3, 29, tzinfo=UTC), False),  # 08:59 IST
        (datetime(2026, 11, 27, 3, 30, tzinfo=UTC), True),  # 09:00 pre-open
        (datetime(2026, 11, 27, 9, 59, tzinfo=UTC), True),  # 15:29
        (datetime(2026, 11, 27, 10, 0, tzinfo=UTC), False),  # 15:30 close
        (datetime(2026, 11, 28, 5, 0, tzinfo=UTC), False),  # Saturday
    ],
)
def test_market_hours(moment: datetime, expected: bool) -> None:
    assert market_hours(moment) is expected


@pytest.mark.parametrize(
    ("minutes", "timeframe", "expected"),
    [
        (0, "1m", 0),
        (7.5, "5m", 5),
        (44, "15m", 30),
        (59.9, "1h", 0),
        (60, "1h", 60),
        (374.5, "30m", 360),  # last, shorter 30m bar starts 15:15
        (380, "1m", 374),  # post-close ticks join the last bar
        (-10, "5m", 0),  # pre-open ticks join the first bar
        (200, "1D", 0),
    ],
)
def test_bucket_start(minutes: float, timeframe: str, expected: int) -> None:
    assert bucket_start(at(minutes), timeframe) == at(expected)  # type: ignore[arg-type]


def test_quote_from_tick_is_consistent() -> None:
    quote = quote_from_tick(tick(1, 101.256, open=0.0, high=0.0, low=0.0))
    assert quote.open == 101.256  # open 0 before the first trade falls back to price
    assert quote.low <= quote.open <= quote.high
    assert quote.change == 2.26 and quote.trend == "up"
    assert quote.change_percent == 2.28


def test_new_bar_counts_volume_from_previous_cumulative() -> None:
    builder = CandleBuilder("1m", None)
    first = builder.apply(tick(0.1, 100.0, volume=5000))
    assert first is not None and first.volume == 0  # nothing known before this tick
    same = builder.apply(tick(0.5, 101.0, volume=5300))
    assert same is not None and (same.open, same.high, same.close, same.volume) == (
        100.0,
        101.0,
        101.0,
        300,
    )
    nxt = builder.apply(tick(1.2, 99.5, volume=5400))
    assert nxt is not None and nxt.time == at(1)
    assert (nxt.open, nxt.low, nxt.volume) == (99.5, 99.5, 100)


def test_seeded_bar_keeps_history_open_high_low_and_volume() -> None:
    seed = MarketCandle(time=at(5), open=98.0, high=103.0, low=97.0, close=100.0, volume=700)
    builder = CandleBuilder("5m", seed)
    candle = builder.apply(tick(6, 101.0, volume=10_000))
    assert candle is not None
    assert (candle.time, candle.open, candle.high, candle.low) == (at(5), 98.0, 103.0, 97.0)
    assert candle.volume == 700
    later = builder.apply(tick(7, 104.0, volume=10_050))
    assert later is not None and later.high == 104.0 and later.volume == 750


def test_older_ticks_are_ignored() -> None:
    builder = CandleBuilder("1m", None)
    assert builder.apply(tick(2, 100.0)) is not None
    assert builder.apply(tick(1, 50.0)) is None


def test_tick_before_last_history_bar_is_ignored() -> None:
    seed = MarketCandle(time=at(10), open=1, high=1, low=1, close=1, volume=1)
    assert CandleBuilder("1m", seed).apply(tick(3, 100.0)) is None


def test_daily_bar_uses_day_fields() -> None:
    builder = CandleBuilder("1D", None)
    candle = builder.apply(tick(30, 102.0, volume=123_456, open=100.0, high=103.0, low=99.0))
    assert candle is not None
    assert (candle.time, candle.open, candle.high, candle.low, candle.close, candle.volume) == (
        OPEN,
        100.0,
        103.0,
        99.0,
        102.0,
        123_456,
    )


def test_index_bars_have_no_volume() -> None:
    builder = CandleBuilder("5m", None)
    candle = builder.apply(tick(1, 24000.0, volume=None))
    assert candle is not None and candle.volume is None


def test_rejected_old_tick_does_not_spoil_the_history_volume_seed() -> None:
    seed = MarketCandle(time=at(5), open=98.0, high=103.0, low=97.0, close=100.0, volume=700)
    builder = CandleBuilder("5m", seed)
    assert builder.apply(tick(2, 99.0, volume=9_000)) is None  # before the history bar
    candle = builder.apply(tick(6, 101.0, volume=10_000))
    assert candle is not None and candle.volume == 700


def test_new_session_restarts_the_volume_baseline() -> None:
    builder = CandleBuilder("1m", None)
    builder.apply(tick(370, 100.0, volume=1_000_000))  # Friday 15:25 IST
    monday = OPEN + timedelta(days=3, seconds=30)
    candle = builder.apply(Tick("NSE:RELIANCE", 101.0, 101.0, 101.0, 101.0, 100.0, 100, monday))
    assert candle is not None and candle.time == OPEN + timedelta(days=3)
    assert candle.volume == 100
