"""Wire models for /api/v1/agents, camelCase as in contracts/openapi.yaml."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

AgentId = Literal["market-scanner", "strategy-analyst", "risk-explainer", "execution-monitor"]
AGENT_IDS: tuple[AgentId, ...] = (
    "market-scanner",
    "strategy-analyst",
    "risk-explainer",
    "execution-monitor",
)
ReasonCode = Literal[
    "LARGE_MOVE",
    "REPLAY_SUMMARY",
    "STOP_LOSS_EXIT",
    "LOSS_LIMIT_REACHED",
    "TRADE_LIMIT_REACHED",
    "ENGINE_HALTED",
    "ORDER_CANCELLED",
    "RECONCILIATION_MISMATCH",
    "RECONCILIATION_MATCHED",
]
Input = Literal["paper-account", "paper-orders", "paper-trades", "paper-replays", "demo-candles"]
Severity = Literal["info", "warning"]
LinkKind = Literal["paper-trade", "paper-order", "paper-replay"]
HealthReason = Literal["NO_PAPER_ACTIVITY", "NOT_YET_EVALUATED", "DATA_STALE"]

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AgentOut(_Wire):
    id: AgentId
    name: str
    description: str
    role: Literal["advisory"] = "advisory"
    inputs: list[Input] = Field(min_length=1)
    reason_codes: list[ReasonCode] = Field(min_length=1)


class AgentRosterOut(_Wire):
    source: Literal["demo"] = "demo"
    environment: Literal["PAPER"] = "PAPER"
    agents: list[AgentOut] = Field(min_length=4, max_length=4)


class AgentHealthOut(_Wire):
    agent_id: AgentId
    status: Literal["ok", "stale", "unavailable"]
    reason_code: HealthReason | None
    last_run_at: datetime | None
    data_as_of: datetime | None
    stale_after_seconds: int = Field(ge=1)


class AgentHealthReportOut(_Wire):
    source: Literal["demo"] = "demo"
    environment: Literal["PAPER"] = "PAPER"
    as_of: datetime
    status: Literal["ok", "degraded", "unavailable"]
    agents: list[AgentHealthOut] = Field(min_length=4, max_length=4)


class AgentLinkOut(_Wire):
    kind: LinkKind
    id: str


class AgentEventOut(_Wire):
    id: str
    agent_id: AgentId
    at: datetime
    data_as_of: datetime
    severity: Severity
    reason_code: ReasonCode
    message: str
    recommendation: str | None
    link: AgentLinkOut | None


class AgentEventPageOut(_Wire):
    source: Literal["demo"] = "demo"
    environment: Literal["PAPER"] = "PAPER"
    items: list[AgentEventOut] = Field(max_length=MAX_LIMIT)
    next_cursor: str | None
