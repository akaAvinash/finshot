"""The fixed alert catalog: every kind with its source, severity, environment
and title, as listed in the Alerts tag of contracts/openapi.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["critical", "warning", "info"]
Source = Literal["paper", "brokers", "agents", "security"]
Environment = Literal["PAPER", "DEMO"]
LinkKind = Literal[
    "paper-trade", "paper-order", "paper-replay", "broker", "broker-connection", "session"
]
Kind = Literal[
    "PAPER_ENGINE_HALTED",
    "PAPER_RISK_LIMIT_REACHED",
    "PAPER_ORDER_CANCELLED",
    "PAPER_STOP_LOSS_EXIT",
    "PAPER_STRATEGY_INACTIVE",
    "PAPER_REPLAY_FINISHED",
    "BROKER_CONNECTION_EXPIRED",
    "BROKER_DISCONNECTED",
    "RECONCILIATION_MISMATCH",
    "NEW_SIGN_IN",
    "SIGNED_OUT_EVERYWHERE",
]

SEVERITIES: tuple[Severity, ...] = ("critical", "warning", "info")
SOURCES: tuple[Source, ...] = ("paper", "brokers", "agents", "security")
LINK_KINDS: tuple[LinkKind, ...] = (
    "paper-trade",
    "paper-order",
    "paper-replay",
    "broker",
    "broker-connection",
    "session",
)


@dataclass(frozen=True)
class KindInfo:
    source: Source
    severity: Severity
    environment: Environment | None
    title: str


CATALOG: dict[Kind, KindInfo] = {
    "PAPER_ENGINE_HALTED": KindInfo("paper", "critical", "PAPER", "Paper engine halted"),
    "PAPER_RISK_LIMIT_REACHED": KindInfo(
        "paper", "critical", "PAPER", "Paper session risk limit reached"
    ),
    "PAPER_ORDER_CANCELLED": KindInfo("paper", "warning", "PAPER", "Paper order cancelled"),
    "PAPER_STOP_LOSS_EXIT": KindInfo("paper", "warning", "PAPER", "Paper stop-loss exit"),
    "PAPER_STRATEGY_INACTIVE": KindInfo(
        "paper", "warning", "PAPER", "Paper engine paused: strategy inactive"
    ),
    "PAPER_REPLAY_FINISHED": KindInfo("paper", "info", "PAPER", "Paper replay finished"),
    "BROKER_CONNECTION_EXPIRED": KindInfo(
        "brokers", "critical", "DEMO", "Demo broker connection expired"
    ),
    "BROKER_DISCONNECTED": KindInfo("brokers", "info", "DEMO", "Demo broker disconnected"),
    "RECONCILIATION_MISMATCH": KindInfo(
        "agents", "warning", "PAPER", "Paper ledger does not reconcile"
    ),
    "NEW_SIGN_IN": KindInfo("security", "info", None, "New sign-in"),
    "SIGNED_OUT_EVERYWHERE": KindInfo("security", "warning", None, "Signed out everywhere"),
}
