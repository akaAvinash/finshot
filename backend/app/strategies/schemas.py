"""Wire models for /api/v1/strategies/preview, camelCase as in contracts/openapi.yaml."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints
from pydantic.alias_generators import to_camel

Instrument = Literal["NIFTY 50", "BANKNIFTY", "FINNIFTY", "RELIANCE", "HDFCBANK", "SBIN"]
Timeframe = Literal["5m", "15m", "30m", "1h", "1D"]
RiskTier = Literal["low", "medium", "high"]
Status = Literal["draft", "active", "paused"]
Backtest = Literal["passed", "failed", "unavailable"]
RiskReview = Literal["approved", "rejected", "pending"]

MAX_STRATEGIES = 100
Bps = Annotated[StrictInt, Field(ge=1, le=10_000)]


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class _Strict(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class StrategyParameters(_Strict):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)]
    instrument: Instrument
    timeframe: Timeframe
    risk_tier: RiskTier
    position_size_bps: Bps
    stop_loss_bps: Bps


class CreateCommand(_Strict):
    action: Literal["create"]
    parameters: StrategyParameters


class SaveDraftCommand(_Strict):
    action: Literal["save-draft"]
    id: str = Field(min_length=1)
    parameters: StrategyParameters


class StatusCommand(_Strict):
    action: Literal["activate", "pause"]
    id: str = Field(min_length=1)


StrategyCommand = Annotated[
    CreateCommand | SaveDraftCommand | StatusCommand, Field(discriminator="action")
]


class StrategyRevisionOut(_Wire):
    parameters: StrategyParameters
    backtest: Backtest
    risk_review: RiskReview


class StrategyVersionOut(_Wire):
    number: int = Field(ge=1)
    activated_at: datetime
    parameters: StrategyParameters
    backtest: Literal["passed"] = "passed"
    risk_review: Literal["approved"] = "approved"


class StrategyOut(_Wire):
    id: str
    status: Status
    draft: StrategyRevisionOut | None
    versions: list[StrategyVersionOut]
    # Always None until paper execution measures results.
    metrics: None = None


class StrategySnapshotOut(_Wire):
    source: Literal["demo"] = "demo"
    environment: Literal["DEMO"] = "DEMO"
    as_of: datetime
    strategies: list[StrategyOut] = Field(max_length=MAX_STRATEGIES)


class StrategyResultOut(_Wire):
    status: Literal["ready"] = "ready"
    data: StrategySnapshotOut
