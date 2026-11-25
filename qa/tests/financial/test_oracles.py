"""Financial oracles: hand-verified examples plus properties (Hypothesis).

These validate the reference side. Engine cross-checks (paper ledger, reports
CSV, backtest metrics vs these oracles) are specified in
docs/qa/FINANCIAL_VALIDATION_PLAN.md and are NOT yet executed.
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from qa.financial_oracles.oracles import (
    ChargeSchedule,
    Fill,
    Side,
    apply_fills,
    daily_loss_breached,
    max_drawdown,
    money,
    order_charges,
    position_size,
    profit_factor,
    simple_return,
    size_from_bps,
    unrealized_pnl,
)

pytestmark = [pytest.mark.suite("financial")]


# ------------------------------------------------- hand-verified examples --
@pytest.mark.severity("critical")
@pytest.mark.req("FIN-PNL-001")
def test_long_round_trip_pnl():
    # Buy 10 @ 100, buy 10 @ 110 -> avg 105; sell 15 @ 120 -> realised 15*15 = 225; 5 open @ 105.
    s = apply_fills([Fill(Side.BUY, 10, D("100")), Fill(Side.BUY, 10, D("110")), Fill(Side.SELL, 15, D("120"))])
    assert (s.quantity, s.average_price, s.realized_pnl) == (5, D("105"), D("225"))
    assert unrealized_pnl(s, D("101.5")) == D("-17.5")


@pytest.mark.severity("critical")
@pytest.mark.req("FIN-PNL-002")
def test_short_and_reversal():
    # Sell 10 @ 200 (short), buy 15 @ 190 -> close 10 for +100, then long 5 @ 190.
    s = apply_fills([Fill(Side.SELL, 10, D("200")), Fill(Side.BUY, 15, D("190"))])
    assert (s.quantity, s.average_price, s.realized_pnl) == (5, D("190"), D("100"))


@pytest.mark.severity("high")
@pytest.mark.req("FIN-CHG-001")
def test_charges_with_explicit_schedule():
    # Synthetic schedule for arithmetic only (not current statutory rates).
    sched = ChargeSchedule(
        brokerage_rate=D("0.0003"),
        brokerage_cap_per_order=D("20"),
        stt_buy_rate=D("0"),
        stt_sell_rate=D("0.00025"),
        exchange_txn_rate=D("0.0000297"),
        sebi_rate=D("0.000001"),
        stamp_buy_rate=D("0.00003"),
        gst_rate=D("0.18"),
        source="synthetic test schedule",
    )
    sell = order_charges(Side.SELL, 100, D("2500"), sched)  # turnover 250000
    assert sell["brokerage"] == D("20.00")  # 75 capped at 20
    assert sell["stt"] == D("62.50")
    assert sell["exchange"] == D("7.43")  # 7.425 -> half-up
    assert sell["sebi"] == D("0.25")
    assert sell["stamp"] == D("0.00")
    assert sell["gst"] == D("4.98")  # (20 + 7.425 + 0.25) * 0.18 = 4.9815, on unrounded fees
    assert sell["total"] == sum(v for k, v in sell.items() if k != "total")


@pytest.mark.severity("high")
@pytest.mark.req("FIN-SIZE-001")
def test_position_sizing_examples():
    # Rs 10,00,000 capital, 1 % risk = 10,000; entry 500, stop 490 -> 1000 units; lot 75 -> 975.
    assert position_size(D("1000000"), D("0.01"), D("500"), D("490")) == 1000
    assert position_size(D("1000000"), D("0.01"), D("500"), D("490"), lot_size=75) == 975
    assert position_size(D("1000000"), D("0.01"), D("500"), D("500")) == 0
    # 600 bps of Rs 10,00,000 at Rs 2,345.60 -> 60,000 / 2345.60 = 25.58 -> 25.
    assert size_from_bps(D("1000000"), 600, D("2345.60")) == 25


@pytest.mark.severity("high")
@pytest.mark.req("FIN-DD-001", "FIN-PF-001", "FIN-RET-001")
def test_drawdown_profit_factor_returns():
    abs_dd, frac = max_drawdown([D(x) for x in ("100", "120", "90", "130", "117")])
    assert abs_dd == D("30") and frac == D("0.25")
    assert profit_factor([D("100"), D("-50"), D("30"), D("-30")]) == D("1.625")
    assert profit_factor([D("10")]) is None
    assert simple_return(D("1000000"), D("1025000")) == D("0.025")


@pytest.mark.severity("critical")
@pytest.mark.req("FIN-RISK-001")
def test_daily_loss_limit_boundary():
    # Paper daily loss limit Rs 25,000 (contract 0.7.0). Exactly at the limit counts as breached.
    assert daily_loss_breached(D("-20000"), D("-5000"), D("25000")) is True
    assert daily_loss_breached(D("-20000"), D("-4999.99"), D("25000")) is False


# -------------------------------------------------------------- properties --
prices = st.decimals(min_value=D("0.05"), max_value=D("100000"), places=2)
qtys = st.integers(min_value=1, max_value=5000)
fills = st.lists(st.builds(Fill, st.sampled_from(list(Side)), qtys, prices), min_size=1, max_size=30)


@pytest.mark.severity("critical")
@pytest.mark.req("FIN-PNL-003")
@settings(max_examples=300, deadline=None)
@given(fills, prices)
def test_pnl_conservation(fs, mark):
    """Realised + unrealised P&L equals cash flow + marked inventory, for any fill sequence."""
    s = apply_fills(fs)
    cash = sum(((-f.price if f.side is Side.BUY else f.price) * f.quantity for f in fs), D(0))
    net_qty = sum((f.quantity if f.side is Side.BUY else -f.quantity) for f in fs)
    assert s.quantity == net_qty
    total = s.realized_pnl + unrealized_pnl(s, mark)
    assert abs(total - (cash + net_qty * mark)) < D("1e-12")


@pytest.mark.severity("high")
@pytest.mark.req("FIN-SIZE-002")
@settings(max_examples=300, deadline=None)
@given(
    st.decimals(min_value=D("1000"), max_value=D("100000000"), places=2),
    st.decimals(min_value=D("0.0001"), max_value=D("0.05"), places=4),
    prices,
    prices,
    st.integers(min_value=1, max_value=1800),
)
def test_position_size_never_exceeds_risk_budget(capital, risk, entry, stop, lot):
    q = position_size(capital, risk, entry, stop, lot)
    assert q >= 0 and q % lot == 0
    assert q * abs(entry - stop) <= capital * risk
    if entry != stop:
        assert (q + lot) * abs(entry - stop) > capital * risk, "one more lot must break the budget"


@pytest.mark.severity("high")
@pytest.mark.req("FIN-DD-002")
@given(st.lists(st.decimals(min_value=D("1"), max_value=D("1e9"), places=2), min_size=1, max_size=200))
def test_drawdown_bounds(equity):
    abs_dd, frac = max_drawdown(equity)
    assert D(0) <= frac < 1
    assert abs_dd <= max(equity) - min(equity)


@pytest.mark.severity("medium")
@pytest.mark.req("FIN-CHG-002")
@given(st.decimals(min_value=D("0"), max_value=D("1e7"), places=4))
def test_money_rounding_half_up_to_paise(x):
    r = money(x)
    assert r.as_tuple().exponent == -2
    assert abs(r - x) <= D("0.005")
