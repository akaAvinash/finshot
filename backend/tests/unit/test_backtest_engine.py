"""The server replay gives the same results as the frontend engine.

tests/unit/data/backtest_golden.json was produced by running
frontend/src/lib/backtesting.ts (replayDemoBacktest) on the frontend's demo
daily candles with Node 22 (--experimental-strip-types). The backend's demo
candles are a port of the same fixture, so both inputs and outputs must match."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from app.backtests.engine import BacktestInputError, Bar, Window, js_round, replay
from app.market.demo import DemoMarketDataProvider

GOLDEN = json.loads((Path(__file__).parent / "data" / "backtest_golden.json").read_text())


def _bars(instrument_id: str) -> list[Bar]:
    candles = asyncio.run(DemoMarketDataProvider().get_candles(instrument_id, "1D"))
    assert candles is not None
    return [Bar(c.time, c.open, c.close) for c in candles.candles]


def _window(config: dict[str, Any]) -> Window:
    return Window(
        start=date.fromisoformat(config["from"]),
        end=date.fromisoformat(config["to"]),
        out_of_sample_from=date.fromisoformat(config["outOfSampleFrom"]),
        capital_paise=config["capitalPaise"],
        fee_bps=config["feeBps"],
        slippage_bps=config["slippageBps"],
    )


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.mark.parametrize("case", GOLDEN, ids=lambda c: c["config"]["instrumentId"])
def test_replay_matches_the_frontend_engine(case: dict[str, Any]) -> None:
    config = case["config"]
    result = replay(_window(config), _bars(config["instrumentId"]), case["positionSizeBps"])
    expected = case["result"]
    # Trade times differ only in how milliseconds are written.
    for trades in (result["trades"], expected["trades"]):
        for trade in trades:
            trade["entryAt"] = _instant(trade["entryAt"])
            trade["exitAt"] = _instant(trade["exitAt"])
    assert result == expected


def test_golden_cases_cover_trades_and_no_trades() -> None:
    counts = [len(case["result"]["trades"]) for case in GOLDEN]
    assert 0 in counts
    assert sum(1 for n in counts if n > 0) >= 3
    assert any(case["result"]["netPnlPaise"] < 0 for case in GOLDEN)


@pytest.mark.parametrize(
    ("start", "oos"),
    [
        ("2026-10-01", "2026-10-05"),  # two warm-up sessions: Oct 1 and Oct 2
        ("2026-10-01", "2026-11-23"),  # one out-of-sample session
        ("2026-10-01", "2026-11-24"),  # no out-of-sample session
    ],
)
def test_too_few_sessions_is_rejected(start: str, oos: str) -> None:
    window = Window(
        start=date.fromisoformat(start),
        end=date(2026, 11, 23),
        out_of_sample_from=date.fromisoformat(oos),
        capital_paise=100_000,
        fee_bps=0,
        slippage_bps=0,
    )
    with pytest.raises(BacktestInputError, match="at least three warm-up"):
        replay(window, _bars("NSE:NIFTY50"), 100)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(2.5, 3), (-2.5, -2), (0.49999999999999994, 0), (-0.5, 0), (1e13 + 0.5, 10_000_000_000_001)],
)
def test_js_round_matches_math_round(value: float, expected: int) -> None:
    assert js_round(value) == expected
