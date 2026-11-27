"""Wire models for /api/v1/auto-trading/paper, camelCase as in contracts/openapi.yaml."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

RECENT_ORDERS = 20
RECENT_TRADES = 50
RECENT_EVENTS = 50
AGENT_NAME = "Paper execution agent"

Engine = Literal["idle", "running", "halted"]


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class _Strict(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class AssignCommand(_Strict):
    action: Literal["assign"]
    strategy_id: str = Field(min_length=1, max_length=64)


class EngineCommand(_Strict):
    action: Literal["start", "pause", "reset"]


class HaltCommand(_Strict):
    action: Literal["halt"]
    confirmation: Literal["STOP"]


PaperCommand = Annotated[AssignCommand | EngineCommand | HaltCommand, Field(discriminator="action")]


class PaperStrategyOut(_Wire):
    id: str
    name: str
    instrument: str
    version: int = Field(ge=1)


class PaperAgentOut(_Wire):
    name: str = AGENT_NAME
    ready: bool


class PaperRiskOut(_Wire):
    status: Literal["approved", "blocked"]
    blocked_reason: (
        Literal["HALTED", "LOSS_LIMIT", "TRADE_LIMIT", "PROFIT_CAP", "CONSECUTIVE_LOSSES"] | None
    )
    daily_loss_paise: int = Field(ge=0)
    loss_limit_paise: int = Field(ge=0)
    trades_today: int = Field(ge=0)
    trade_limit: int = Field(ge=1)
    consecutive_losses: int = Field(ge=0)
    controls_revision: int = Field(ge=0)


class PaperAccountOut(_Wire):
    capital_paise: int = Field(ge=0)
    cash_paise: int = Field(ge=0)
    equity_paise: int = Field(ge=0)
    position_quantity: int = Field(ge=0)
    per_trade_risk_paise: int = Field(ge=0)


class PaperReplayOut(_Wire):
    session_date: date | None
    sessions_done: int = Field(ge=0)
    sessions_total: int = Field(ge=0)
    finished: bool


class PaperOrderOut(_Wire):
    id: str
    instrument: str
    side: Literal["Buy", "Sell"]
    quantity: int = Field(ge=1)
    limit_paise: int = Field(ge=0)
    approval: Literal["approved"] = "approved"
    status: Literal["queued", "filled", "cancelled"]


class PaperTradeOut(_Wire):
    id: str
    instrument: str
    side: Literal["Buy", "Sell"]
    quantity: int = Field(ge=1)
    fill_paise: int = Field(ge=1)
    fees_paise: int = Field(ge=0)
    pnl_paise: int
    filled_at: datetime
    reason: Literal["entry", "signal-exit", "stop-loss", "take-profit", "end-of-replay"]


class PaperEventOut(_Wire):
    id: str
    at: datetime
    message: str


class PaperSnapshotOut(_Wire):
    source: Literal["demo"] = "demo"
    environment: Literal["PAPER"] = "PAPER"
    as_of: datetime
    engine: Engine
    strategies: list[PaperStrategyOut]
    strategy_id: str | None
    agent: PaperAgentOut
    risk: PaperRiskOut
    account: PaperAccountOut
    replay: PaperReplayOut
    orders: list[PaperOrderOut] = Field(max_length=RECENT_ORDERS)
    trades: list[PaperTradeOut] = Field(max_length=RECENT_TRADES)
    events: list[PaperEventOut] = Field(max_length=RECENT_EVENTS)


class PaperReadyOut(_Wire):
    status: Literal["ready"] = "ready"
    data: PaperSnapshotOut


class PaperEmptyOut(_Wire):
    status: Literal["empty"] = "empty"
