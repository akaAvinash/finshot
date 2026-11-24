"""Automatic strategy checks (contracts/openapi.yaml, sendStrategyCommand).

Both checks are server rules; nobody approves a strategy by hand. The
numbers are configuration examples for synthetic demo data, not advice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.strategies.schemas import StrategyParameters


@dataclass(frozen=True)
class TierLimits:
    max_position_size_bps: int
    max_stop_loss_bps: int
    min_max_drawdown_bps: int


TIER_LIMITS: dict[str, TierLimits] = {
    "low": TierLimits(600, 100, -500),
    "medium": TierLimits(1000, 200, -1000),
    "high": TierLimits(1500, 300, -2000),
}

MIN_OUT_OF_SAMPLE_SESSIONS = 10
MIN_TRADES = 1
# A run counts only with costs at least the paper engine's.
MIN_FEE_BPS = 3
MIN_SLIPPAGE_BPS = 5


def risk_review(parameters: StrategyParameters) -> Literal["approved", "rejected"]:
    limits = TIER_LIMITS[parameters.risk_tier]
    within = (
        parameters.position_size_bps <= limits.max_position_size_bps
        and parameters.stop_loss_bps <= limits.max_stop_loss_bps
    )
    return "approved" if within else "rejected"


def run_counts(
    *,
    config: dict[str, Any],
    run_parameters: dict[str, Any],
    draft_parameters: dict[str, Any] | None,
    draft_instrument_id: str | None,
) -> bool:
    """Whether a completed draft run may set the draft's backtest check.

    `config` is the run's stored wire config (camelCase)."""
    return (
        draft_parameters is not None
        and run_parameters == draft_parameters
        and draft_instrument_id is not None
        and config.get("instrumentId") == draft_instrument_id
        and int(config.get("feeBps", -1)) >= MIN_FEE_BPS
        and int(config.get("slippageBps", -1)) >= MIN_SLIPPAGE_BPS
    )


def backtest_verdict(
    parameters: StrategyParameters, result: dict[str, Any]
) -> Literal["passed", "failed"]:
    limits = TIER_LIMITS[parameters.risk_tier]
    passed = (
        len(result.get("points", [])) >= MIN_OUT_OF_SAMPLE_SESSIONS
        and len(result.get("trades", [])) >= MIN_TRADES
        and int(result["netPnlPaise"]) >= 0
        and int(result["maxDrawdownBps"]) >= limits.min_max_drawdown_bps
    )
    return "passed" if passed else "failed"
