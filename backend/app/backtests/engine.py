"""Deterministic demo replay, ported from frontend/src/lib/backtesting.ts.

The arithmetic follows the frontend line by line, including JavaScript's
Math.round, so a run on the server gives the same result as the frontend mock
for the same candles. tests/unit/test_backtest_engine.py checks this against
results produced by the frontend code."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

BASIS_POINTS = 10_000
LOOKBACK = 3
TOO_FEW_SESSIONS = "Choose at least three warm-up sessions and two out-of-sample sessions."


class BacktestInputError(ValueError):
    """The window cannot be replayed. The message is safe to show."""


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    close: float


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    out_of_sample_from: date
    capital_paise: int
    fee_bps: int
    slippage_bps: int


@dataclass
class _Position:
    entry_at: datetime
    quantity: int
    entry_paise: int
    fee_paise: int


def js_round(value: float) -> int:
    """Math.round: nearest integer, halves toward +infinity."""
    floor = math.floor(value)
    return floor + 1 if value - floor >= 0.5 else floor


def _fee_on(gross_paise: int, rate: int) -> int:
    return math.ceil(gross_paise * rate / BASIS_POINTS)


def window_bars(window: Window, candles: Sequence[Bar]) -> tuple[list[Bar], int]:
    """The candles inside the window and the index of the first out-of-sample
    session. Raises BacktestInputError when there are too few sessions."""
    bars = [c for c in candles if window.start <= c.time.date() <= window.end]
    holdout = next(
        (i for i, c in enumerate(bars) if c.time.date() >= window.out_of_sample_from), -1
    )
    if holdout < LOOKBACK or len(bars) - holdout < 2:
        raise BacktestInputError(TOO_FEW_SESSIONS)
    return bars, holdout


def replay(window: Window, candles: Sequence[Bar], position_size_bps: int) -> dict[str, Any]:
    """Returns the result in wire shape (camelCase keys, JSON-ready values)."""
    bars, holdout = window_bars(window, candles)
    slip = window.slippage_bps
    fee = window.fee_bps
    cash = window.capital_paise
    peak = cash
    position: _Position | None = None
    trades: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []

    for index in range(holdout, len(bars)):
        bar = bars[index]
        previous = bars[index - LOOKBACK : index]
        last_close = previous[LOOKBACK - 1].close
        moving_average = sum(c.close for c in previous) / LOOKBACK
        long_signal = last_close > moving_average
        last_session = index == len(bars) - 1
        open_paise = js_round(bar.open * 100)

        if position is not None and (not long_signal or last_session):
            exit_paise = math.floor(open_paise * (BASIS_POINTS - slip) / BASIS_POINTS)
            proceeds = exit_paise * position.quantity
            exit_fee = _fee_on(proceeds, fee)
            fees_paise = position.fee_paise + exit_fee
            cash += proceeds - exit_fee
            trades.append(
                {
                    "id": f"trade-{len(trades) + 1}",
                    "entryAt": _iso(position.entry_at),
                    "exitAt": _iso(bar.time),
                    "quantity": position.quantity,
                    "entryPaise": position.entry_paise,
                    "exitPaise": exit_paise,
                    "feesPaise": fees_paise,
                    "pnlPaise": proceeds - position.entry_paise * position.quantity - fees_paise,
                }
            )
            position = None
        elif position is None and long_signal and not last_session:
            entry_paise = math.ceil(open_paise * (BASIS_POINTS + slip) / BASIS_POINTS)
            budget = math.floor(cash * position_size_bps / BASIS_POINTS)
            quantity = math.floor(budget * BASIS_POINTS / (entry_paise * (BASIS_POINTS + fee)))
            if quantity > 0:
                gross = entry_paise * quantity
                fee_paise = _fee_on(gross, fee)
                cash -= gross + fee_paise
                position = _Position(bar.time, quantity, entry_paise, fee_paise)

        held = js_round(bar.close * 100) * position.quantity if position is not None else 0
        equity_paise = cash + held
        peak = max(peak, equity_paise)
        # `-x || 0` in the frontend turns -0 into 0; Python ints have no -0.
        drawdown_bps = -js_round((peak - equity_paise) * BASIS_POINTS / peak)
        points.append(
            {
                "date": bar.time.date().isoformat(),
                "equityPaise": equity_paise,
                "drawdownBps": drawdown_bps,
            }
        )

    net_pnl = cash - window.capital_paise
    wins = sum(1 for t in trades if t["pnlPaise"] > 0)
    return {
        "endingEquityPaise": cash,
        "netPnlPaise": net_pnl,
        "returnBps": js_round(net_pnl * BASIS_POINTS / window.capital_paise),
        "maxDrawdownBps": min(p["drawdownBps"] for p in points),
        "winRateBps": js_round(wins * BASIS_POINTS / len(trades)) if trades else None,
        "totalFeesPaise": sum(t["feesPaise"] for t in trades),
        "points": points,
        "trades": trades,
    }


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
