"""Deterministic paper replay: one demo daily session per step.

Pure functions over integers (paise), so the rules in contracts/openapi.yaml
(sendPaperCommand) can be unit tested without a database. The signal is the
backtest engine's: long when a close is above the average of the last three
closes, that one included."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.backtests.engine import js_round

BASIS_POINTS = 10_000
LOOKBACK = 3

# Fixed paper limits: configuration examples for demo data, not advice. They are
# also the ceilings a user's Trade Controls can only tighten.
CAPITAL_PAISE = 100_000_000  # ₹10,00,000
LOSS_LIMIT_PAISE = 2_500_000  # ₹25,000 per session
TRADE_LIMIT = 10  # fills per session
PER_TRADE_RISK_BPS = 100  # 1% of capital
PER_TRADE_RISK_PAISE = CAPITAL_PAISE * PER_TRADE_RISK_BPS // BASIS_POINTS
FEE_BPS = 3
SLIPPAGE_BPS = 5

Side = Literal["Buy", "Sell"]
Reason = Literal["entry", "signal-exit", "stop-loss", "take-profit", "end-of-replay"]
BlockedReason = Literal["LOSS_LIMIT", "TRADE_LIMIT", "PROFIT_CAP", "CONSECUTIVE_LOSSES"]


@dataclass(frozen=True)
class Limits:
    """The limits the risk engine applies to one user's paper account: their
    Trade Controls, or the ceilings above when they never saved. Position size
    and stop loss are already narrowed with the strategy version's."""

    loss_limit_paise: int = LOSS_LIMIT_PAISE
    trade_limit: int = TRADE_LIMIT
    profit_limit_paise: int | None = None
    max_consecutive_losses: int = 0  # 0 is off
    take_profit_bps: int | None = None
    per_trade_risk_paise: int = PER_TRADE_RISK_PAISE


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class Session:
    time: datetime
    open: float
    low: float
    close: float
    high: float


@dataclass
class QueuedOrder:
    side: Side
    quantity: int


@dataclass
class State:
    cash_paise: int
    position_quantity: int = 0
    position_entry_paise: int | None = None
    position_stop_paise: int | None = None
    position_target_paise: int | None = None
    position_fees_paise: int = 0
    session_pnl_paise: int = 0
    # Highest realised P&L reached at any point of the session, and the run of
    # losing exits at its end (entries neither count nor reset it).
    session_peak_pnl_paise: int = 0
    session_loss_streak: int = 0
    session_fills: int = 0
    sessions_done: int = 0


@dataclass(frozen=True)
class Fill:
    side: Side
    quantity: int
    fill_paise: int
    fees_paise: int
    pnl_paise: int
    reason: Reason
    at: datetime


@dataclass(frozen=True)
class NewOrder:
    side: Side
    quantity: int
    limit_paise: int


@dataclass
class StepResult:
    # What happened to the order queued before this session, if any.
    queued_outcome: Literal["filled", "cancelled"] | None = None
    filled_quantity: int = 0
    fills: list[Fill] = field(default_factory=list)
    new_order: NewOrder | None = None
    finished: bool = False
    # A buy signal was blocked by the session risk limits.
    risk_blocked: bool = False
    events: list[str] = field(default_factory=list)


def paise(price: float) -> int:
    return js_round(price * 100)


def fee_on(gross_paise: int) -> int:
    return math.ceil(gross_paise * FEE_BPS / BASIS_POINTS)


def buy_price(reference_paise: int) -> int:
    return math.ceil(reference_paise * (BASIS_POINTS + SLIPPAGE_BPS) / BASIS_POINTS)


def sell_price(reference_paise: int) -> int:
    return math.floor(reference_paise * (BASIS_POINTS - SLIPPAGE_BPS) / BASIS_POINTS)


def stop_price(entry_paise: int, stop_loss_bps: int) -> int:
    return math.floor(entry_paise * (BASIS_POINTS - stop_loss_bps) / BASIS_POINTS)


def affordable(budget_paise: int, price_paise: int) -> int:
    """Largest quantity whose notional plus entry fee fits the budget."""
    if budget_paise <= 0 or price_paise <= 0:
        return 0
    quantity = budget_paise * BASIS_POINTS // (price_paise * (BASIS_POINTS + FEE_BPS))
    while quantity > 0 and price_paise * quantity + fee_on(price_paise * quantity) > budget_paise:
        quantity -= 1
    return quantity


def session_loss(state: State) -> int:
    return max(0, -state.session_pnl_paise)


def target_price(entry_paise: int, take_profit_bps: int) -> int:
    return math.ceil(entry_paise * (BASIS_POINTS + take_profit_bps) / BASIS_POINTS)


def blocked_reason(state: State, limits: Limits = DEFAULT_LIMITS) -> BlockedReason | None:
    """Why the risk engine blocks new buys this session, or None. The first
    that applies, in the order of `PaperRisk.blockedReason`."""
    if session_loss(state) >= limits.loss_limit_paise:
        return "LOSS_LIMIT"
    if state.session_fills >= limits.trade_limit:
        return "TRADE_LIMIT"
    if (
        limits.profit_limit_paise is not None
        and state.session_peak_pnl_paise >= limits.profit_limit_paise
    ):
        return "PROFIT_CAP"
    if (
        limits.max_consecutive_losses > 0
        and state.session_loss_streak >= limits.max_consecutive_losses
    ):
        return "CONSECUTIVE_LOSSES"
    return None


def risk_blocked(state: State, limits: Limits = DEFAULT_LIMITS) -> bool:
    return blocked_reason(state, limits) is not None


def buy_quantity(
    cash_paise: int,
    close_paise: int,
    size_bps: int,
    stop_loss_bps: int,
    per_trade_risk_paise: int = PER_TRADE_RISK_PAISE,
) -> int:
    reference = buy_price(close_paise)
    by_size = affordable(cash_paise * size_bps // BASIS_POINTS, reference)
    per_unit = reference - stop_price(reference, stop_loss_bps)
    by_risk = per_trade_risk_paise // per_unit if per_unit > 0 else by_size
    return min(by_size, by_risk)


def rupees(amount_paise: int) -> str:
    return f"₹{amount_paise / 100:,.2f}"


def _sell(state: State, fill_paise: int, reason: Reason, at: datetime) -> Fill:
    quantity = state.position_quantity
    proceeds = fill_paise * quantity
    exit_fee = fee_on(proceeds)
    entry = state.position_entry_paise or 0
    pnl = proceeds - entry * quantity - state.position_fees_paise - exit_fee
    state.cash_paise += proceeds - exit_fee
    state.position_quantity = 0
    state.position_entry_paise = None
    state.position_stop_paise = None
    state.position_target_paise = None
    state.position_fees_paise = 0
    state.session_pnl_paise += pnl
    state.session_peak_pnl_paise = max(state.session_peak_pnl_paise, state.session_pnl_paise)
    state.session_loss_streak = state.session_loss_streak + 1 if pnl < 0 else 0
    state.session_fills += 1
    return Fill("Sell", quantity, fill_paise, exit_fee, pnl, reason, at)


def step(
    state: State,
    sessions: Sequence[Session],
    queued: QueuedOrder | None,
    *,
    size_bps: int,
    stop_loss_bps: int,
    symbol: str,
    limits: Limits = DEFAULT_LIMITS,
) -> StepResult:
    """Replays session `state.sessions_done`, mutating `state`."""
    index = state.sessions_done
    bar = sessions[index]
    open_paise, low_paise, close_paise = paise(bar.open), paise(bar.low), paise(bar.close)
    high_paise = paise(bar.high)
    state.session_pnl_paise = 0
    state.session_peak_pnl_paise = 0
    state.session_loss_streak = 0
    state.session_fills = 0
    out = StepResult()

    # 1. The order queued at the previous close fills at this open.
    if queued is not None:
        if queued.side == "Buy":
            fill = buy_price(open_paise)
            quantity = min(queued.quantity, affordable(state.cash_paise, fill))
            if quantity == 0:
                out.queued_outcome = "cancelled"
                out.events.append("Buy order cancelled: cash does not cover the open price.")
            else:
                gross = fill * quantity
                fees = fee_on(gross)
                state.cash_paise -= gross + fees
                state.position_quantity = quantity
                state.position_entry_paise = fill
                state.position_stop_paise = stop_price(fill, stop_loss_bps)
                state.position_target_paise = (
                    None
                    if limits.take_profit_bps is None
                    else target_price(fill, limits.take_profit_bps)
                )
                state.position_fees_paise = fees
                state.session_fills += 1
                out.queued_outcome = "filled"
                out.filled_quantity = quantity
                out.fills.append(Fill("Buy", quantity, fill, fees, 0, "entry", bar.time))
        elif state.position_quantity > 0:
            out.queued_outcome = "filled"
            out.filled_quantity = state.position_quantity
            out.fills.append(_sell(state, sell_price(open_paise), "signal-exit", bar.time))
        else:
            out.queued_outcome = "cancelled"

    # 2. Stop-loss against this session's low; if it was not reached, the
    # Trade Controls take-profit against this session's high.
    stop = state.position_stop_paise
    # The target follows the current control, so turning take-profit off (or
    # changing it) while a position is open applies from the next session.
    target = (
        None
        if limits.take_profit_bps is None or state.position_entry_paise is None
        else target_price(state.position_entry_paise, limits.take_profit_bps)
    )
    state.position_target_paise = target if state.position_quantity > 0 else None
    if state.position_quantity > 0 and stop is not None and low_paise <= stop:
        out.fills.append(_sell(state, sell_price(min(open_paise, stop)), "stop-loss", bar.time))
    elif state.position_quantity > 0 and target is not None and high_paise >= target:
        out.fills.append(_sell(state, sell_price(max(open_paise, target)), "take-profit", bar.time))

    last = index == len(sessions) - 1
    if last:
        # 4. The replay ends flat.
        if state.position_quantity > 0:
            out.fills.append(_sell(state, sell_price(close_paise), "end-of-replay", bar.time))
        out.finished = True
    elif index >= LOOKBACK - 1:
        # 3. Signal at the close, once three closes exist.
        window = sessions[index - LOOKBACK + 1 : index + 1]
        long_signal = bar.close > sum(s.close for s in window) / LOOKBACK
        if long_signal and state.position_quantity == 0:
            if risk_blocked(state, limits):
                out.risk_blocked = True
                out.events.append("Buy signal blocked by the session risk limits.")
            else:
                quantity = buy_quantity(
                    state.cash_paise,
                    close_paise,
                    size_bps,
                    stop_loss_bps,
                    limits.per_trade_risk_paise,
                )
                if quantity == 0:
                    out.events.append("Buy signal skipped: the risk engine sized it to zero.")
                else:
                    out.new_order = NewOrder("Buy", quantity, close_paise)
        elif not long_signal and state.position_quantity > 0:
            out.new_order = NewOrder("Sell", state.position_quantity, close_paise)

    for f in out.fills:
        verb = "Bought" if f.side == "Buy" else "Sold"
        out.events.append(f"{verb} {f.quantity} {symbol} at {rupees(f.fill_paise)} ({f.reason}).")
    if out.new_order is not None:
        out.events.append(
            f"Queued {out.new_order.side.lower()} of {out.new_order.quantity} {symbol}"
            " for the next open."
        )
    if out.finished:
        out.events.append("Replay finished. The engine is idle.")
    state.sessions_done = index + 1
    return out
