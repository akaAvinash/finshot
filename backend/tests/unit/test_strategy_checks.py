"""Automatic strategy check rules (contracts/openapi.yaml, sendStrategyCommand)."""

from __future__ import annotations

from typing import Any

import pytest

from app.strategies.rules import backtest_verdict, risk_review, run_counts
from app.strategies.schemas import StrategyParameters

BASE: dict[str, Any] = {
    "name": "Rule check",
    "description": "",
    "instrument": "NIFTY 50",
    "timeframe": "1D",
    "riskTier": "medium",
    "positionSizeBps": 1000,
    "stopLossBps": 200,
}


def params(**overrides: Any) -> StrategyParameters:
    return StrategyParameters.model_validate({**BASE, **overrides})


def result(
    points: int = 10, trades: int = 1, net: int = 0, drawdown: int = -1000
) -> dict[str, Any]:
    return {
        "points": [{}] * points,
        "trades": [{}] * trades,
        "netPnlPaise": net,
        "maxDrawdownBps": drawdown,
    }


@pytest.mark.parametrize(
    ("tier", "size", "stop", "expected"),
    [
        ("low", 600, 100, "approved"),
        ("low", 601, 100, "rejected"),
        ("low", 600, 101, "rejected"),
        ("medium", 1000, 200, "approved"),
        ("medium", 1001, 1, "rejected"),
        ("high", 1500, 300, "approved"),
        ("high", 1, 301, "rejected"),
    ],
)
def test_risk_review_limits(tier: str, size: int, stop: int, expected: str) -> None:
    assert risk_review(params(riskTier=tier, positionSizeBps=size, stopLossBps=stop)) == expected


@pytest.mark.parametrize(
    ("tier", "overrides", "expected"),
    [
        ("medium", {}, "passed"),
        ("medium", {"points": 9}, "failed"),
        ("medium", {"trades": 0}, "failed"),
        ("medium", {"net": -1}, "failed"),
        ("medium", {"drawdown": -1001}, "failed"),
        ("low", {"drawdown": -500}, "passed"),
        ("low", {"drawdown": -501}, "failed"),
        ("high", {"drawdown": -2000}, "passed"),
        ("high", {"drawdown": -2001}, "failed"),
    ],
)
def test_backtest_verdict_thresholds(tier: str, overrides: dict[str, int], expected: str) -> None:
    assert backtest_verdict(params(riskTier=tier), result(**overrides)) == expected


def test_run_counts_only_for_the_same_draft_instrument_and_costs() -> None:
    draft = params().model_dump(mode="json")
    config = {"instrumentId": "NSE:NIFTY50", "feeBps": 3, "slippageBps": 5}

    def counts(**kwargs: Any) -> bool:
        args: dict[str, Any] = {
            "config": config,
            "run_parameters": draft,
            "draft_parameters": draft,
            "draft_instrument_id": "NSE:NIFTY50",
            **kwargs,
        }
        return run_counts(**args)

    assert counts()
    assert not counts(draft_parameters=None)
    assert not counts(run_parameters={**draft, "stop_loss_bps": 199})
    assert not counts(draft_instrument_id=None)
    assert not counts(config={**config, "instrumentId": "NSE:BANKNIFTY"})
    assert not counts(config={**config, "feeBps": 2})
    assert not counts(config={**config, "slippageBps": 4})
