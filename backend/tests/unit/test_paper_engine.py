"""Paper replay rules (contracts/openapi.yaml, sendPaperCommand), one session per step."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.paper import engine
from app.paper.engine import QueuedOrder, Session, State, step

T0 = datetime(2026, 10, 1, 3, 45, tzinfo=UTC)


def sessions(*bars: tuple[float, float, float]) -> list[Session]:
    """(open, low, close) in rupees, one per day."""
    return [Session(T0 + timedelta(days=i), o, lo, c) for i, (o, lo, c) in enumerate(bars)]


def run(state: State, bars: list[Session], queued: QueuedOrder | None = None, **kw: int):  # type: ignore[no-untyped-def]
    return step(
        state,
        bars,
        queued,
        size_bps=kw.get("size_bps", 1000),
        stop_loss_bps=kw.get("stop_loss_bps", 200),
        symbol="SBIN",
    )


RISING = sessions(
    (100, 99, 100), (101, 100, 101), (102, 101, 103), (104, 103, 105), (106, 105, 106)
)


def test_no_signal_during_warm_up() -> None:
    state = State(cash_paise=engine.CAPITAL_PAISE)
    for _ in range(2):
        out = run(state, RISING)
        assert out.new_order is None and out.fills == []
    assert state.sessions_done == 2
    out = run(state, RISING)  # third close: 103 > avg(100, 101, 103)
    assert out.new_order is not None and out.new_order.side == "Buy"
    assert out.new_order.limit_paise == 10_300


def test_buy_sizing_is_the_smaller_of_size_and_risk() -> None:
    # Size limit: 10% of ₹10,00,000 at ~₹103.06 -> 970. Risk: ₹10,000 over a
    # 2% stop (₹2.07 per unit) -> 4830. Size wins.
    assert engine.buy_quantity(engine.CAPITAL_PAISE, 10_300, 1000, 200) == 970
    # 100% sizing (9700 units) with a 2% stop: risk wins (₹10,000 / ₹2.07 = 4830).
    ref = engine.buy_price(10_300)
    per_unit = ref - engine.stop_price(ref, 200)
    assert engine.buy_quantity(engine.CAPITAL_PAISE, 10_300, 10_000, 200) == (
        engine.PER_TRADE_RISK_PAISE // per_unit
    )
    assert engine.PER_TRADE_RISK_PAISE // per_unit == 4830


def test_queued_buy_fills_at_open_with_slippage_and_fees() -> None:
    state = State(cash_paise=engine.CAPITAL_PAISE, sessions_done=3)
    out = run(state, RISING, QueuedOrder("Buy", 970))
    (fill,) = [f for f in out.fills if f.reason == "entry"]
    price = engine.buy_price(10_400)
    assert price == 10_406  # ceil(10400 * 1.0005)
    assert (fill.side, fill.quantity, fill.fill_paise) == ("Buy", 970, price)
    assert fill.fees_paise == engine.fee_on(price * 970)
    assert state.cash_paise == engine.CAPITAL_PAISE - price * 970 - fill.fees_paise
    assert state.position_stop_paise == engine.stop_price(price, 200)
    assert out.queued_outcome == "filled" and state.session_fills == 1


def test_gap_up_reduces_or_cancels_the_buy() -> None:
    state = State(cash_paise=10_000_00, sessions_done=3)  # ₹10,000
    out = run(state, RISING, QueuedOrder("Buy", 1_000))
    assert out.queued_outcome == "filled"
    assert out.filled_quantity == engine.affordable(10_000_00, engine.buy_price(10_400))
    assert state.cash_paise >= 0
    state = State(cash_paise=50_00, sessions_done=3)  # ₹50: not one unit
    out = run(state, RISING, QueuedOrder("Buy", 5))
    assert out.queued_outcome == "cancelled" and out.fills == []
    assert any("cancelled" in e for e in out.events)


def test_stop_loss_sells_at_the_lower_of_open_and_stop() -> None:
    bars = sessions((100, 99, 100), (100, 99, 100), (100, 99, 100), (95, 90, 96), (96, 95, 96))
    state = State(
        cash_paise=0,
        position_quantity=10,
        position_entry_paise=10_000,
        position_stop_paise=9_800,
        position_fees_paise=30,
        sessions_done=3,
    )
    out = run(state, bars)
    (fill,) = out.fills
    assert fill.reason == "stop-loss"
    assert fill.fill_paise == engine.sell_price(9_500)  # gapped below the stop
    exit_fee = engine.fee_on(fill.fill_paise * 10)
    assert fill.pnl_paise == fill.fill_paise * 10 - 100_000 - 30 - exit_fee
    assert state.position_quantity == 0 and state.session_pnl_paise == fill.pnl_paise


def test_falling_close_queues_a_sell_that_fills_next_open() -> None:
    bars = sessions((100, 99, 100), (101, 100, 101), (102, 101, 99), (98, 97, 97), (97, 96, 97))
    state = State(
        cash_paise=0,
        position_quantity=5,
        position_entry_paise=10_000,
        position_stop_paise=5_000,
        sessions_done=2,
    )
    out = run(state, bars)
    assert out.new_order is not None and (out.new_order.side, out.new_order.quantity) == ("Sell", 5)
    out = run(state, bars, QueuedOrder("Sell", 5))
    (fill,) = out.fills
    assert (fill.reason, fill.fill_paise) == ("signal-exit", engine.sell_price(9_800))


def test_last_session_ends_flat_and_finishes() -> None:
    state = State(
        cash_paise=0,
        position_quantity=3,
        position_entry_paise=10_000,
        position_stop_paise=5_000,
        sessions_done=4,
    )
    out = run(state, RISING)
    (fill,) = out.fills
    assert (fill.reason, fill.fill_paise) == ("end-of-replay", engine.sell_price(10_600))
    assert out.finished and out.new_order is None and state.sessions_done == 5
    assert out.events[-1] == "Replay finished. The engine is idle."


def test_session_loss_limit_blocks_new_buys() -> None:
    bars = sessions(
        (100, 99, 100), (101, 100, 101), (102, 101, 103), (90, 50, 104), (105, 104, 105)
    )
    # A large position stopped out at session 4 loses more than ₹25,000.
    state = State(
        cash_paise=0,
        position_quantity=10_000,
        position_entry_paise=10_000,
        position_stop_paise=9_500,
        sessions_done=3,
    )
    out = run(state, bars)
    assert engine.session_loss(state) >= engine.LOSS_LIMIT_PAISE
    assert out.new_order is None
    assert "Buy signal blocked by the session risk limits." in out.events
    assert out.risk_blocked  # the paper service raises PAPER_RISK_LIMIT_REACHED on this
    # The next session starts its counters from zero.
    nxt = run(state, bars)
    assert not nxt.risk_blocked
    assert (state.session_pnl_paise, state.session_fills) == (0, 0)


def test_risk_blocked_by_fill_count() -> None:
    state = State(cash_paise=1, session_fills=engine.TRADE_LIMIT)
    assert engine.risk_blocked(state)
    state.session_fills = engine.TRADE_LIMIT - 1
    assert not engine.risk_blocked(state)
