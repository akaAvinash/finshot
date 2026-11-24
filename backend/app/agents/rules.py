"""The four advisory agents' rules, as pure functions over observations.

Each pass the service reads the user's paper data into an `Observation`,
calls `evaluate`, inserts the returned events (idempotently, by dedupe key)
and stores the returned memory. Nothing here writes paper data, sends a
command or changes a risk limit: the output is text for a person to read."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any

from app.agents.schemas import AgentId, AgentOut, LinkKind, ReasonCode, Severity
from app.paper import engine as paper

# A move is large when it is at least MOVE_MULTIPLE times the average
# absolute close-to-close move of the MOVE_WINDOW sessions before it.
MOVE_WINDOW = 5
MOVE_MULTIPLE = 2

ROSTER: tuple[AgentOut, ...] = (
    AgentOut(
        id="market-scanner",
        name="Market scanner",
        description=(
            "Flags replayed demo sessions of the assigned instrument whose close-to-close"
            " move is at least twice the average of the five sessions before."
        ),
        inputs=["paper-account", "demo-candles"],
        reason_codes=["LARGE_MOVE"],
    ),
    AgentOut(
        id="strategy-analyst",
        name="Strategy analyst",
        description="Summarises each finished paper replay: fills, winning sells, realised P&L.",
        inputs=["paper-account", "paper-trades", "paper-replays"],
        reason_codes=["REPLAY_SUMMARY"],
    ),
    AgentOut(
        id="risk-explainer",
        name="Risk explainer",
        description=(
            "Explains risk outcomes the deterministic risk engine already applied:"
            " stop-loss exits, session limits reached and halts."
        ),
        inputs=["paper-account", "paper-trades"],
        reason_codes=[
            "STOP_LOSS_EXIT",
            "LOSS_LIMIT_REACHED",
            "TRADE_LIMIT_REACHED",
            "ENGINE_HALTED",
        ],
    ),
    AgentOut(
        id="execution-monitor",
        name="Execution monitor",
        description=(
            "Watches paper order outcomes and checks that the paper account matches its ledger."
        ),
        inputs=["paper-account", "paper-orders", "paper-trades"],
        reason_codes=["ORDER_CANCELLED", "RECONCILIATION_MISMATCH", "RECONCILIATION_MATCHED"],
    ),
)


@dataclass(frozen=True)
class Trade:
    id: str
    seq: int
    replay: int
    instrument: str
    side: str
    quantity: int
    fill_paise: int
    pnl_paise: int
    reason: str
    filled_at: datetime


@dataclass(frozen=True)
class CancelledOrder:
    id: str
    replay: int
    instrument: str
    side: str
    quantity: int
    cancelled_at: datetime


@dataclass(frozen=True)
class Close:
    at: datetime
    close_paise: int


@dataclass(frozen=True)
class ReplaySummary:
    replay: int
    finished_at: datetime
    fills: int
    winning_sells: int
    realised_paise: int
    last_fill_at: datetime | None


@dataclass(frozen=True)
class Observation:
    replay: int
    engine: str
    changed_at: datetime  # the paper account's updated_at
    symbol: str | None
    sessions_done: int
    closes: Sequence[Close]  # the assigned instrument's demo closes, oldest first
    trades: Sequence[Trade]  # fills after memory's tradeSeq, by seq
    cancelled: Sequence[CancelledOrder]
    reconciled: bool | None  # None before the first assignment
    summaries: Sequence[ReplaySummary]  # finished replays not yet summarised


@dataclass(frozen=True)
class NewEvent:
    agent_id: AgentId
    dedupe_key: str
    reason_code: ReasonCode
    severity: Severity
    message: str
    recommendation: str | None
    link_kind: LinkKind | None
    link_id: str | None
    data_as_of: datetime


@dataclass
class Memory:
    trade_seq: int = 0
    engine: str | None = None
    reconciled: bool = True
    scan_replay: int = 0
    scan_done: int = 0

    @classmethod
    def load(cls, raw: dict[str, Any]) -> Memory:
        return cls(
            trade_seq=int(raw.get("tradeSeq", 0)),
            engine=raw.get("engine"),
            reconciled=bool(raw.get("reconciled", True)),
            scan_replay=int(raw.get("scanReplay", 0)),
            scan_done=int(raw.get("scanDone", 0)),
        )

    def dump(self) -> dict[str, Any]:
        return {
            "tradeSeq": self.trade_seq,
            "engine": self.engine,
            "reconciled": self.reconciled,
            "scanReplay": self.scan_replay,
            "scanDone": self.scan_done,
        }


@dataclass
class Result:
    events: list[NewEvent] = field(default_factory=list)
    memory: Memory = field(default_factory=Memory)


def _stamp(at: datetime) -> str:
    return at.isoformat()


def evaluate(obs: Observation, memory: Memory) -> Result:
    out = Result(memory=Memory(**memory.__dict__))
    _scan(obs, out)
    _analyse(obs, out)
    _explain_risk(obs, out)
    _monitor(obs, out)
    return out


def _move(closes: Sequence[Close], index: int) -> Fraction:
    """Absolute close-to-close move of session `index`, as a fraction."""
    previous = closes[index - 1].close_paise
    return Fraction(abs(closes[index].close_paise - previous), previous)


def _scan(obs: Observation, out: Result) -> None:
    mem = out.memory
    start = mem.scan_done if mem.scan_replay == obs.replay else 0
    done = min(obs.sessions_done, len(obs.closes))
    if any(c.close_paise <= 0 for c in obs.closes[:done]):
        done = 0  # pragma: no cover - demo closes are positive
    for index in range(max(start, MOVE_WINDOW + 1), done):
        move = _move(obs.closes, index)
        average = (
            sum((_move(obs.closes, i) for i in range(index - MOVE_WINDOW, index)), Fraction(0))
            / MOVE_WINDOW
        )
        if move == 0 or move < MOVE_MULTIPLE * average:
            continue
        previous, current = obs.closes[index - 1], obs.closes[index]
        direction = "higher" if current.close_paise > previous.close_paise else "lower"
        ratio = (
            ""
            if average == 0
            else f", {float(move / average):.1f}x its average move over the previous"
            f" {MOVE_WINDOW} sessions"
        )
        out.events.append(
            NewEvent(
                agent_id="market-scanner",
                dedupe_key=f"move:{obs.replay}:{index}",
                reason_code="LARGE_MOVE",
                severity="info",
                message=(
                    f"{obs.symbol} closed {float(move) * 100:.2f}% {direction} than the previous"
                    f" demo session ({paper.rupees(previous.close_paise)} to"
                    f" {paper.rupees(current.close_paise)}){ratio}."
                ),
                recommendation=None,
                link_kind="paper-replay",
                link_id=str(obs.replay),
                data_as_of=current.at,
            )
        )
    mem.scan_replay = obs.replay
    mem.scan_done = max(start, done)


def _analyse(obs: Observation, out: Result) -> None:
    for summary in obs.summaries:
        out.events.append(
            NewEvent(
                agent_id="strategy-analyst",
                dedupe_key=f"replay:{summary.replay}",
                reason_code="REPLAY_SUMMARY",
                severity="info",
                message=(
                    f"Replay {summary.replay} finished with {summary.fills} fill(s),"
                    f" {summary.winning_sells} winning sell(s) and realised P&L of"
                    f" {paper.rupees(summary.realised_paise)}."
                ),
                recommendation=(
                    "Compare this replay with the strategy's backtest before changing parameters."
                ),
                link_kind="paper-replay",
                link_id=str(summary.replay),
                data_as_of=summary.last_fill_at or summary.finished_at,
            )
        )


def _explain_risk(obs: Observation, out: Result) -> None:
    mem = out.memory
    sessions: dict[tuple[int, datetime], list[Trade]] = {}
    for trade in obs.trades:
        sessions.setdefault((trade.replay, trade.filled_at), []).append(trade)
        mem.trade_seq = max(mem.trade_seq, trade.seq)
        if trade.reason == "stop-loss":
            out.events.append(
                NewEvent(
                    agent_id="risk-explainer",
                    dedupe_key=f"stop:{trade.id}",
                    reason_code="STOP_LOSS_EXIT",
                    severity="warning",
                    message=(
                        f"The stop-loss sold {trade.quantity} {trade.instrument} at"
                        f" {paper.rupees(trade.fill_paise)} for a realised P&L of"
                        f" {paper.rupees(trade.pnl_paise)}."
                    ),
                    recommendation=(
                        "Review the version's stop-loss distance against recent demo"
                        " ranges before the next replay."
                    ),
                    link_kind="paper-trade",
                    link_id=trade.id,
                    data_as_of=trade.filled_at,
                )
            )
    for (replay, at), fills in sessions.items():
        pnl = 0
        loss_seen = trades_seen = False
        for count, trade in enumerate(fills, start=1):
            pnl += trade.pnl_paise
            if not loss_seen and max(0, -pnl) >= paper.LOSS_LIMIT_PAISE:
                loss_seen = True
                out.events.append(
                    _limit(
                        "LOSS_LIMIT_REACHED",
                        f"loss:{replay}:{_stamp(at)}",
                        f"The session's realised loss reached the"
                        f" {paper.rupees(paper.LOSS_LIMIT_PAISE)} limit; the risk engine"
                        " queues no new buys for the rest of this session.",
                        trade,
                    )
                )
            if not trades_seen and count >= paper.TRADE_LIMIT:
                trades_seen = True
                out.events.append(
                    _limit(
                        "TRADE_LIMIT_REACHED",
                        f"fills:{replay}:{_stamp(at)}",
                        f"The session reached {paper.TRADE_LIMIT} fills; the risk engine"
                        " queues no new buys for the rest of this session.",
                        trade,
                    )
                )
    if obs.engine == "halted" and mem.engine != "halted":
        out.events.append(
            NewEvent(
                agent_id="risk-explainer",
                dedupe_key=f"halt:{obs.replay}:{_stamp(obs.changed_at)}",
                reason_code="ENGINE_HALTED",
                severity="warning",
                message=(
                    "The paper engine is halted by the kill switch; queued orders were cancelled."
                ),
                recommendation="Review the open position and recent events before resetting.",
                link_kind="paper-replay" if obs.replay >= 1 else None,
                link_id=str(obs.replay) if obs.replay >= 1 else None,
                data_as_of=obs.changed_at,
            )
        )
    mem.engine = obs.engine


def _limit(code: ReasonCode, key: str, message: str, trade: Trade) -> NewEvent:
    return NewEvent(
        agent_id="risk-explainer",
        dedupe_key=key,
        reason_code=code,
        severity="warning",
        message=message,
        recommendation=(
            "Review position size and stop-loss before the next session. The limit"
            " is fixed and only the risk engine applies it."
        ),
        link_kind="paper-trade",
        link_id=trade.id,
        data_as_of=trade.filled_at,
    )


def _monitor(obs: Observation, out: Result) -> None:
    mem = out.memory
    for order in obs.cancelled:
        out.events.append(
            NewEvent(
                agent_id="execution-monitor",
                dedupe_key=f"cancel:{order.id}",
                reason_code="ORDER_CANCELLED",
                severity="info",
                message=(
                    f"A queued paper {order.side.lower()} of {order.quantity}"
                    f" {order.instrument} was cancelled."
                ),
                recommendation=None,
                link_kind="paper-order",
                link_id=order.id,
                data_as_of=order.cancelled_at,
            )
        )
    if obs.reconciled is None:
        return
    if not obs.reconciled and mem.reconciled:
        out.events.append(
            NewEvent(
                agent_id="execution-monitor",
                dedupe_key=f"mismatch:{obs.replay}:{_stamp(obs.changed_at)}",
                reason_code="RECONCILIATION_MISMATCH",
                severity="warning",
                message=f"Replay {obs.replay}'s paper account does not match its ledger.",
                recommendation="Do not rely on this replay's figures until it matches again.",
                link_kind="paper-replay",
                link_id=str(obs.replay),
                data_as_of=obs.changed_at,
            )
        )
    elif obs.reconciled and not mem.reconciled:
        out.events.append(
            NewEvent(
                agent_id="execution-monitor",
                dedupe_key=f"matched:{obs.replay}:{_stamp(obs.changed_at)}",
                reason_code="RECONCILIATION_MATCHED",
                severity="info",
                message=f"Replay {obs.replay}'s paper account matches its ledger again.",
                recommendation=None,
                link_kind="paper-replay",
                link_id=str(obs.replay),
                data_as_of=obs.changed_at,
            )
        )
    mem.reconciled = obs.reconciled
