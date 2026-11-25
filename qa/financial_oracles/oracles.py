"""Independent financial reference calculations (exact Decimal arithmetic).

These are the expected-value side of financial tests. They are written from
first principles and never call product code. Rounding is explicit: money is
rounded to paise (0.01) with ROUND_HALF_UP only where a statement or ledger
would round; intermediate values stay exact.

Charge rates are inputs, never defaults: Indian statutory charges (STT,
exchange fees, SEBI fee, stamp duty, GST) change over time, so a test must pass
the schedule it means and cite where it came from.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum
from fractions import Fraction

PAISE = Decimal("0.01")


def money(x: Decimal) -> Decimal:
    return x.quantize(PAISE, rounding=ROUND_HALF_UP)


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Fill:
    side: Side
    quantity: int
    price: Decimal


@dataclass(frozen=True)
class PositionState:
    quantity: int  # signed: >0 long, <0 short
    average_price: Decimal  # of the open quantity
    realized_pnl: Decimal


def apply_fills(fills: Iterable[Fill]) -> PositionState:
    """Weighted-average cost position; realised P&L on the closed quantity.

    Reversal through zero closes the old side at its average and opens the
    remainder at the fill price.
    """
    # Exact rational arithmetic inside the oracle: no rounding of the cost basis
    # before realised P&L is computed. Converted to Decimal only on output.
    qty = 0
    avg = Fraction(0)
    realized = Fraction(0)
    for f in fills:
        if f.quantity <= 0:
            raise ValueError("fill quantity must be positive")
        signed = f.quantity if f.side is Side.BUY else -f.quantity
        if qty == 0 or (qty > 0) == (signed > 0):
            new_qty = qty + signed
            avg = (avg * abs(qty) + Fraction(f.price) * abs(signed)) / abs(new_qty)
            qty = new_qty
            continue
        closing = min(abs(qty), abs(signed))
        direction = 1 if qty > 0 else -1
        realized += (Fraction(f.price) - avg) * closing * direction
        remainder = abs(signed) - closing
        qty += signed
        if qty == 0:
            avg = Fraction(0)
        elif remainder > 0:
            avg = Fraction(f.price)
    return PositionState(qty, _dec(avg), _dec(realized))


def _dec(x: Fraction) -> Decimal:
    """Fraction to Decimal at 34 significant digits (far below one paise of error)."""
    with localcontext() as ctx:
        ctx.prec = 34
        return Decimal(x.numerator) / Decimal(x.denominator)


def unrealized_pnl(state: PositionState, mark: Decimal) -> Decimal:
    return (mark - state.average_price) * state.quantity


@dataclass(frozen=True)
class ChargeSchedule:
    """All rates as fractions of turnover (e.g. Decimal('0.001') = 0.1 %)."""

    brokerage_rate: Decimal
    brokerage_cap_per_order: Decimal | None
    stt_buy_rate: Decimal
    stt_sell_rate: Decimal
    exchange_txn_rate: Decimal
    sebi_rate: Decimal
    stamp_buy_rate: Decimal
    gst_rate: Decimal  # applied to brokerage + exchange + SEBI fees
    source: str  # where these numbers came from; required


def order_charges(side: Side, quantity: int, price: Decimal, s: ChargeSchedule) -> dict[str, Decimal]:
    turnover = price * quantity
    brokerage = turnover * s.brokerage_rate
    if s.brokerage_cap_per_order is not None:
        brokerage = min(brokerage, s.brokerage_cap_per_order)
    stt = turnover * (s.stt_buy_rate if side is Side.BUY else s.stt_sell_rate)
    exchange = turnover * s.exchange_txn_rate
    sebi = turnover * s.sebi_rate
    stamp = turnover * s.stamp_buy_rate if side is Side.BUY else Decimal(0)
    gst = (brokerage + exchange + sebi) * s.gst_rate
    parts = {
        "brokerage": money(brokerage),
        "stt": money(stt),
        "exchange": money(exchange),
        "sebi": money(sebi),
        "stamp": money(stamp),
        "gst": money(gst),
    }
    parts["total"] = sum(parts.values(), Decimal(0))
    return parts


def position_size(capital: Decimal, risk_fraction: Decimal, entry: Decimal, stop: Decimal, lot_size: int = 1) -> int:
    """Largest whole-lot quantity whose loss at the stop stays within capital * risk_fraction."""
    per_unit = abs(entry - stop)
    if per_unit == 0 or capital <= 0 or risk_fraction <= 0:
        return 0
    budget = capital * risk_fraction
    units = (budget / per_unit).to_integral_value(rounding=ROUND_DOWN)
    lots = int(units) // lot_size
    return lots * lot_size


def size_from_bps(capital: Decimal, position_bps: int, price: Decimal, lot_size: int = 1) -> int:
    """Quantity for a notional of capital * bps / 10_000, rounded down to whole lots."""
    notional = capital * Decimal(position_bps) / Decimal(10_000)
    units = int((notional / price).to_integral_value(rounding=ROUND_DOWN))
    return (units // lot_size) * lot_size


def max_drawdown(equity: Sequence[Decimal]) -> tuple[Decimal, Decimal]:
    """(absolute, fraction of peak). Fraction is 0 for an empty or never-positive peak."""
    peak = None
    worst_abs = Decimal(0)
    worst_frac = Decimal(0)
    for v in equity:
        peak = v if peak is None or v > peak else peak
        dd = peak - v
        if dd > worst_abs:
            worst_abs = dd
        if peak > 0 and dd / peak > worst_frac:
            worst_frac = dd / peak
    return worst_abs, worst_frac


def profit_factor(trade_pnls: Iterable[Decimal]) -> Decimal | None:
    """Gross profit / gross loss. None when there are no losing trades (undefined, not infinite)."""
    gains = losses = Decimal(0)
    for p in trade_pnls:  # one pass: works for one-shot iterators too
        if p > 0:
            gains += p
        elif p < 0:
            losses -= p
    return None if losses == 0 else gains / losses


def simple_return(start: Decimal, end: Decimal) -> Decimal:
    if start == 0:
        raise ZeroDivisionError("start value is zero")
    return (end - start) / start


def daily_loss_breached(realized_today: Decimal, unrealized: Decimal, limit: Decimal) -> bool:
    """True once today's loss (realised + open) reaches the limit (limit is a positive amount)."""
    return -(realized_today + unrealized) >= limit
