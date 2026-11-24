"""Pure agent rules (contract 0.9.0, listAgents): what each agent records."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from app.agents import rules
from app.agents.rules import CancelledOrder, Close, Memory, Observation, ReplaySummary, Trade
from app.agents.schemas import AgentRosterOut
from app.paper import engine as paper

T0 = datetime(2026, 1, 1, 3, 45, tzinfo=UTC)


def day(n: int) -> datetime:
    return T0 + timedelta(days=n)


def obs(**overrides: Any) -> Observation:
    base = Observation(
        replay=1,
        engine="running",
        finished=False,
        changed_at=day(100),
        symbol="SBIN",
        sessions_done=0,
        closes=[],
        trades=[],
        cancelled=[],
        reconciled=True,
        summary=None,
    )
    return replace(base, **overrides)


def trade(seq: int, **overrides: Any) -> Trade:
    base = Trade(
        id=f"00000000-0000-0000-0000-{seq:012d}",
        seq=seq,
        replay=1,
        instrument="SBIN",
        side="Sell",
        quantity=10,
        fill_paise=80_000,
        pnl_paise=0,
        reason="signal-exit",
        filled_at=day(1),
    )
    return replace(base, **overrides)


def codes(result: rules.Result) -> list[str]:
    return [e.reason_code for e in result.events]


def test_roster_is_the_contract_roster() -> None:
    roster = AgentRosterOut(agents=list(rules.ROSTER))
    assert [a.id for a in roster.agents] == [
        "market-scanner",
        "strategy-analyst",
        "risk-explainer",
        "execution-monitor",
    ]
    assert {a.role for a in roster.agents} == {"advisory"}


# ------------------------------------------------------------- market scanner

CALM = [100_000, 100_100, 100_000, 100_100, 100_000, 100_100]  # 0.1% moves


def closes(values: list[int]) -> list[Close]:
    return [Close(day(i), v) for i, v in enumerate(values)]


def test_scanner_flags_a_move_twice_the_recent_average() -> None:
    series = closes([*CALM, 100_400])  # 0.3%: over twice the average 0.1%
    result = rules.evaluate(obs(closes=series, sessions_done=7), Memory())
    assert codes(result) == ["LARGE_MOVE"]
    event = result.events[0]
    assert event.agent_id == "market-scanner"
    assert event.data_as_of == day(6)
    assert (event.link_kind, event.link_id) == ("paper-replay", "1")
    assert "higher" in event.message and "SBIN" in event.message
    assert result.memory.scan_done == 7


def test_scanner_ignores_ordinary_moves_and_unreplayed_sessions() -> None:
    calm = rules.evaluate(obs(closes=closes([*CALM, 100_150]), sessions_done=7), Memory())
    assert codes(calm) == []
    # The big move exists in the history but has not been replayed yet.
    early = rules.evaluate(obs(closes=closes([*CALM, 90_000]), sessions_done=6), Memory())
    assert codes(early) == []
    # Fewer than six earlier closes: never checked.
    short = rules.evaluate(
        obs(closes=closes([100_000, 100_100, 200_000]), sessions_done=3), Memory()
    )
    assert codes(short) == []


def test_scanner_checks_each_session_once_per_replay() -> None:
    series = closes([*CALM, 95_000])
    first = rules.evaluate(obs(closes=series, sessions_done=7), Memory())
    assert codes(first) == ["LARGE_MOVE"]
    again = rules.evaluate(obs(closes=series, sessions_done=7), first.memory)
    assert codes(again) == []
    # A new replay scans from the start again.
    fresh = rules.evaluate(obs(replay=2, closes=series, sessions_done=7), first.memory)
    assert codes(fresh) == ["LARGE_MOVE"]
    assert fresh.events[0].dedupe_key == "move:2:6"


# ----------------------------------------------------------- strategy analyst


def test_analyst_summarises_a_finished_replay() -> None:
    summary = ReplaySummary(fills=4, winning_sells=1, realised_paise=-12_345, last_fill_at=day(9))
    result = rules.evaluate(obs(finished=True, engine="idle", summary=summary), Memory())
    assert codes(result) == ["REPLAY_SUMMARY"]
    event = result.events[0]
    assert event.dedupe_key == "replay:1"
    assert event.data_as_of == day(9)
    assert "4 fill(s)" in event.message and "1 winning" in event.message
    assert paper.rupees(-12_345) in event.message
    assert rules.evaluate(obs(summary=summary), Memory()).events == []  # not finished


# -------------------------------------------------------------- risk explainer


def test_stop_loss_exit_links_the_fill() -> None:
    stop = trade(7, reason="stop-loss", pnl_paise=-5_000)
    result = rules.evaluate(obs(trades=[trade(6, side="Buy", reason="entry"), stop]), Memory())
    assert codes(result) == ["STOP_LOSS_EXIT"]
    event = result.events[0]
    assert (event.link_kind, event.link_id) == ("paper-trade", stop.id)
    assert event.severity == "warning"
    assert result.memory.trade_seq == 7


def test_session_limits_fire_once_per_session() -> None:
    losing = [
        trade(1, pnl_paise=-paper.LOSS_LIMIT_PAISE // 2, filled_at=day(3)),
        trade(2, pnl_paise=-paper.LOSS_LIMIT_PAISE // 2, filled_at=day(3)),
        trade(3, pnl_paise=-paper.LOSS_LIMIT_PAISE, filled_at=day(3)),
    ]
    result = rules.evaluate(obs(trades=losing), Memory())
    assert codes(result) == ["LOSS_LIMIT_REACHED"]
    assert result.events[0].link_id == losing[1].id  # the fill that reached it
    busy = [trade(i, filled_at=day(4)) for i in range(1, paper.TRADE_LIMIT + 1)]
    result = rules.evaluate(obs(trades=busy), Memory())
    assert codes(result) == ["TRADE_LIMIT_REACHED"]
    assert result.events[0].link_id == busy[-1].id
    # Below the limits in another session: nothing.
    calm = [trade(1, pnl_paise=-1, filled_at=day(5))]
    assert codes(rules.evaluate(obs(trades=calm), Memory())) == []


def test_halt_is_reported_on_the_transition_only() -> None:
    first = rules.evaluate(obs(engine="halted"), Memory(engine="running"))
    assert codes(first) == ["ENGINE_HALTED"]
    assert codes(rules.evaluate(obs(engine="halted"), first.memory)) == []
    later = rules.evaluate(obs(engine="idle"), first.memory)
    halted_again = rules.evaluate(obs(engine="halted", changed_at=day(101)), later.memory)
    assert codes(halted_again) == ["ENGINE_HALTED"]
    assert halted_again.events[0].dedupe_key != first.events[0].dedupe_key


# ----------------------------------------------------------- execution monitor


def test_cancelled_orders_and_reconciliation_transitions() -> None:
    order = CancelledOrder("o-1", 1, "SBIN", "Buy", 5, day(2))
    result = rules.evaluate(obs(cancelled=[order], reconciled=False), Memory())
    assert codes(result) == ["ORDER_CANCELLED", "RECONCILIATION_MISMATCH"]
    assert (result.events[0].link_kind, result.events[0].link_id) == ("paper-order", "o-1")
    still = rules.evaluate(obs(reconciled=False), result.memory)
    assert codes(still) == []
    restored = rules.evaluate(obs(reconciled=True), still.memory)
    assert codes(restored) == ["RECONCILIATION_MATCHED"]
    # Before any assignment there is nothing to reconcile.
    assert codes(rules.evaluate(obs(replay=0, reconciled=None), Memory())) == []


def test_memory_round_trips_and_tolerates_an_empty_row() -> None:
    memory = Memory(trade_seq=9, engine="halted", reconciled=False, scan_replay=2, scan_done=5)
    assert Memory.load(memory.dump()) == memory
    assert Memory.load({}) == Memory()


def test_evaluation_never_mutates_the_given_memory() -> None:
    memory = Memory()
    rules.evaluate(obs(engine="halted", trades=[trade(3)]), memory)
    assert memory == Memory()
