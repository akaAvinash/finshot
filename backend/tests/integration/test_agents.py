"""Advisory agents (contract 0.9.0): listAgents, getAgentHealth, listAgentEvents
and the evaluation worker, over real PostgreSQL and Redis.

The app runs without its background workers; tests replay paper sessions with
`tick_once()` and evaluate with `run_once()` under the fake clock, so every
event is deterministic. One test runs the real agent worker."""

from __future__ import annotations

import base64
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient

from app.agents.rules import MOVE_MULTIPLE, MOVE_WINDOW
from app.agents.service import AgentService, encode_cursor
from app.paper import engine
from tests.integration.test_paper import (
    STRATEGY_COMMANDS,
    TICK,
    _alembic,
    _db,
    active_strategy,
    check,
    ok,
    sessions,
    tick,
)
from tests.integration.test_paper import (
    contract as contract,  # fixture
)
from tests.support import OTHER_PHONE, Browser, FakeClock, db_rows

pytestmark = pytest.mark.integration

ROSTER = "/api/v1/agents"
HEALTH = f"{ROSTER}/health"
EVENTS = f"{ROSTER}/events"
PAPER_COMMANDS = "/api/v1/auto-trading/paper/commands"
STALE = 30
AGENT_IDS = ["market-scanner", "strategy-analyst", "risk-explainer", "execution-monitor"]


@pytest.fixture(autouse=True)
def _no_worker_heartbeat() -> Iterator[None]:
    # agent_worker has no user to cascade from, so clear it per test.
    db_rows(_db(), "DELETE FROM agent_worker")
    yield


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    return make_app(
        paper_worker_enabled=False,
        backtest_worker_enabled=False,
        agent_worker_enabled=False,
        paper_tick_seconds=TICK,
        agent_stale_after_seconds=STALE,
    )


def agents(client: TestClient) -> AgentService:
    service: AgentService = client.app.state.agents  # type: ignore[attr-defined]
    return service


def evaluate(client: TestClient) -> int:
    """Run agent passes until every user is evaluated; returns users evaluated."""
    assert client.portal is not None
    count = 0
    while client.portal.call(agents(client).run_once):
        count += 1
    return count


def get_ok(browser: Browser, path: str, **params: Any) -> dict[str, Any]:
    response = browser.get(path, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def all_events(browser: Browser, contract: Any, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(1000):
        query = dict(params) if cursor is None else {**params, "cursor": cursor}
        page = get_ok(browser, EVENTS, **query)
        check(contract, "AgentEventPage", page)
        items.extend(page["items"])
        cursor = page["nextCursor"]
        if cursor is None:
            return items
    raise AssertionError("pagination did not end")


def assigned(client: TestClient, phone: str | None = None) -> Browser:
    browser = Browser(client)
    if phone is None:
        browser.login()
    else:
        browser.login(phone=phone)
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    return browser


def replay_all(client: TestClient, clock: FakeClock, *, evaluate_each: bool) -> None:
    budget = len(sessions("NSE:SBIN"))
    for _ in range(budget + 1):
        if not tick(client):
            break
        if evaluate_each:
            evaluate(client)
        clock.advance(TICK)
    evaluate(client)


def expected_moves() -> list[int]:
    """Session indexes the scanner must flag on the SBIN demo closes."""
    closes = [engine.paise(s.close) for s in sessions("NSE:SBIN")]
    moves = [abs(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    flagged = []
    for index in range(MOVE_WINDOW + 1, len(closes)):
        recent = moves[index - 1 - MOVE_WINDOW : index - 1]
        move = moves[index - 1]
        if move > 0 and move * MOVE_WINDOW >= MOVE_MULTIPLE * sum(recent) - 1e-12:
            flagged.append(index)
    assert flagged, "the SBIN demo history should have unusual moves"
    return flagged


# ------------------------------------------------------------- access and errors


def test_every_endpoint_requires_a_session(browser: Browser, contract: Any) -> None:
    for path in (ROSTER, HEALTH, EVENTS):
        response = browser.get(path)
        assert response.status_code == 401, path
        check(contract, "AgentError", response.json())
        assert response.json()["code"] == "UNAUTHENTICATED"
    # The session check runs before query validation.
    assert browser.get(EVENTS, params={"limit": "0", "cursor": "!"}).status_code == 401


def test_disabled_is_503_and_starts_no_worker(
    make_app: Callable[..., TestClient], contract: Any
) -> None:
    # The worker setting is on: only AGENTS_ENABLED keeps the worker off.
    client = make_app(
        agents_enabled=False,
        agent_worker_enabled=True,
        agent_worker_poll_seconds=0.05,
        paper_worker_enabled=False,
        backtest_worker_enabled=False,
    )
    browser = assigned(client)
    for path in (ROSTER, HEALTH, EVENTS):
        response = browser.get(path)
        assert response.status_code == 503, path
        check(contract, "AgentError", response.json())
        assert response.json()["code"] == "AGENTS_UNAVAILABLE"
    time.sleep(0.5)  # ten worker polls, had it started
    assert db_rows(_db(), "SELECT 1 FROM agent_runs") == []
    assert db_rows(_db(), "SELECT 1 FROM agent_worker") == []


@pytest.mark.parametrize(
    "params",
    [
        {"agentId": "order-bot"},
        {"limit": "0"},
        {"limit": "101"},
        {"limit": "ten"},
        {"cursor": ""},
        {"cursor": "not-a-cursor"},
        {"cursor": "x" * 129},
        {"cursor": base64.urlsafe_b64encode(b"v1:*:0").decode().rstrip("=")},
        {"cursor": base64.urlsafe_b64encode(b"v1:*:12").decode()},  # padded: not ours
        {"cursor": encode_cursor("risk-explainer", 5)},  # issued for another filter
        {"cursor": encode_cursor(None, 5), "agentId": "risk-explainer"},
    ],
)
def test_invalid_event_queries_are_400(
    browser: Browser, contract: Any, params: dict[str, str]
) -> None:
    browser.login()
    response = browser.get(EVENTS, params=params)
    assert response.status_code == 400, response.text
    check(contract, "AgentError", response.json())
    assert response.json()["code"] == "INVALID_REQUEST"


def test_agent_endpoints_are_read_only(client: TestClient, clock: FakeClock) -> None:
    browser = assigned(client)
    ok(browser, {"action": "start"})
    tick(client)
    evaluate(client)

    def snapshot() -> list[Any]:
        return [
            db_rows(_db(), f"SELECT * FROM {table} ORDER BY 1")
            for table in (
                "agent_events",
                "agent_runs",
                "agent_worker",
                "paper_accounts",
                "paper_orders",
                "paper_trades",
                "paper_events",
                "paper_replays",
                "audit_events",
            )
        ]

    before = snapshot()
    clock.advance(STALE * 3)
    for path in (ROSTER, HEALTH, EVENTS):
        assert browser.get(path).status_code == 200
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            response = browser.send(method, path, json={})
            assert response.status_code == 405, (method, path)
    assert snapshot() == before


def test_agents_never_write_paper_data(client: TestClient, clock: FakeClock) -> None:
    browser = assigned(client)
    ok(browser, {"action": "start"})
    for _ in range(4):
        tick(client)
        clock.advance(TICK)
    paper_tables = (
        "paper_accounts",
        "paper_replays",
        "paper_replay_finishes",
        "paper_orders",
        "paper_trades",
        "paper_events",
    )

    def paper_rows() -> list[Any]:
        return [db_rows(_db(), f"SELECT * FROM {t} ORDER BY 1") for t in paper_tables]

    before = paper_rows()
    assert before[1], "the baseline should hold the replay row"
    assert evaluate(client) == 1
    assert paper_rows() == before
    assert db_rows(_db(), "SELECT count(*) AS n FROM agent_events")[0]["n"] >= 0


# -------------------------------------------------------------------- roster


def test_roster_matches_the_contract(browser: Browser, contract: Any) -> None:
    browser.login()
    body = get_ok(browser, ROSTER)
    check(contract, "AgentRoster", body)
    assert (body["source"], body["environment"]) == ("demo", "PAPER")
    assert [a["id"] for a in body["agents"]] == AGENT_IDS
    assert {a["role"] for a in body["agents"]} == {"advisory"}
    codes = {c for a in body["agents"] for c in a["reasonCodes"]}
    assert codes == set(contract["components"]["schemas"]["AgentReasonCode"]["enum"])


# -------------------------------------------------------------------- health


def health(browser: Browser, contract: Any) -> dict[str, Any]:
    body = get_ok(browser, HEALTH)
    check(contract, "AgentHealthReport", body)
    assert [a["agentId"] for a in body["agents"]] == AGENT_IDS
    assert {a["staleAfterSeconds"] for a in body["agents"]} == {STALE}
    # Every agent is evaluated together, so they agree.
    assert len({(a["status"], a["reasonCode"]) for a in body["agents"]}) == 1
    return body


def state(body: dict[str, Any]) -> tuple[str, str, str | None]:
    agent = body["agents"][0]
    return body["status"], agent["status"], agent["reasonCode"]


def test_health_without_paper_activity_is_unavailable(client: TestClient, contract: Any) -> None:
    browser = Browser(client)
    browser.login()
    body = health(browser, contract)
    assert state(body) == ("unavailable", "unavailable", "NO_PAPER_ACTIVITY")
    assert body["agents"][0]["lastRunAt"] is None
    assert body["agents"][0]["dataAsOf"] is None
    # A strategy that was never assigned is not paper activity either.
    active_strategy(browser)
    assert state(health(browser, contract))[2] == "NO_PAPER_ACTIVITY"


def test_health_follows_the_ordered_rules(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = assigned(client)
    # Never evaluated and no worker pass ever ended: stale at once.
    assert state(health(browser, contract)) == ("degraded", "stale", "DATA_STALE")
    # A worker pass just ended elsewhere (fresh heartbeat): not yet evaluated.
    db_rows(_db(), "INSERT INTO agent_worker (id, pass_ended_at) VALUES (1, :at)", at=clock())
    assert state(health(browser, contract)) == (
        "unavailable",
        "unavailable",
        "NOT_YET_EVALUATED",
    )
    # The pending change ages past the deadline.
    clock.advance(STALE + 1)
    db_rows(_db(), "UPDATE agent_worker SET pass_ended_at = :at", at=clock())
    assert state(health(browser, contract)) == ("degraded", "stale", "DATA_STALE")

    evaluate(client)
    body = health(browser, contract)
    assert state(body) == ("ok", "ok", None)
    agent = body["agents"][0]
    account = db_rows(_db(), "SELECT updated_at FROM paper_accounts")[0]
    assert agent["dataAsOf"] == account["updated_at"].isoformat().replace("+00:00", "Z")
    assert agent["lastRunAt"] == clock().isoformat().replace("+00:00", "Z")
    # Unchanged data never goes stale, however long it sits.
    clock.advance(STALE * 5)
    assert state(health(browser, contract))[1] == "ok"


def test_a_stopped_worker_goes_stale_while_data_keeps_changing(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = assigned(client)
    ok(browser, {"action": "start"})
    evaluate(client)
    assert state(health(browser, contract))[1] == "ok"
    # The worker stops; the paper engine changes every few seconds.
    statuses = []
    for _ in range(STALE // int(TICK) + 2):
        clock.advance(TICK)
        assert tick(client)
        statuses.append(state(health(browser, contract))[1:])
    assert statuses[0] == ("ok", None)  # pending, within the deadline
    assert statuses[-1] == ("stale", "DATA_STALE")
    # The worker catches up.
    evaluate(client)
    assert state(health(browser, contract))[1] == "ok"


# -------------------------------------------------------------------- events


def test_a_full_replay_records_deterministic_events(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = assigned(client)
    ok(browser, {"action": "start"})
    replay_all(client, clock, evaluate_each=True)
    items = all_events(browser, contract)
    assert all((e["agentId"], e["reasonCode"]) for e in items)
    by_code: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_code.setdefault(item["reasonCode"], []).append(item)
    bars = sessions("NSE:SBIN")
    moves = [m for m in reversed(by_code.pop("LARGE_MOVE"))]
    assert [m["dataAsOf"] for m in moves] == [
        bars[i].time.isoformat().replace("+00:00", "Z") for i in expected_moves()
    ]
    assert all(m["link"] == {"kind": "paper-replay", "id": "1"} for m in moves)
    (summary,) = by_code.pop("REPLAY_SUMMARY")
    assert summary["agentId"] == "strategy-analyst"
    assert summary["link"] == {"kind": "paper-replay", "id": "1"}
    trades = db_rows(_db(), "SELECT pnl_paise, side FROM paper_trades")
    assert f"{len(trades)} fill(s)" in summary["message"]
    assert engine.rupees(sum(t["pnl_paise"] for t in trades)) in summary["message"]
    # No stop-loss, limit, halt, cancel or mismatch happened in this replay.
    assert by_code == {}
    # Newest first by sequence: the summary came last.
    assert items[0]["reasonCode"] == "REPLAY_SUMMARY"
    assert {(e["source"], e["environment"]) for e in [get_ok(browser, EVENTS)]} == {
        ("demo", "PAPER")
    }
    # Evaluating again records nothing new.
    db_rows(_db(), "UPDATE agent_runs SET data_as_of = NULL, state = '{}'::jsonb")
    evaluate(client)
    assert len(all_events(browser, contract)) == len(items)


def test_pagination_is_stable_while_events_arrive(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = assigned(client)
    ok(browser, {"action": "start"})
    replay_all(client, clock, evaluate_each=True)
    everything = all_events(browser, contract)
    assert len(everything) >= 3
    first = get_ok(browser, EVENTS, limit=1)
    assert first["items"] == everything[:1]
    # A new event (a halt) is recorded between pages.
    ok(browser, {"action": "halt", "confirmation": "STOP"})
    evaluate(client)
    rest = []
    cursor = first["nextCursor"]
    for _ in range(1000):
        if cursor is None:
            break
        page = get_ok(browser, EVENTS, limit=2, cursor=cursor)
        assert len(page["items"]) <= 2
        assert page["nextCursor"] != cursor, "pagination did not advance"
        rest.extend(page["items"])
        cursor = page["nextCursor"]
    else:
        raise AssertionError("pagination did not end")
    assert first["items"] + rest == everything
    fresh = get_ok(browser, EVENTS, limit=1)["items"][0]
    assert (fresh["reasonCode"], fresh["agentId"]) == ("ENGINE_HALTED", "risk-explainer")
    assert get_ok(browser, EVENTS, limit=100)["nextCursor"] is None


def test_agent_filter_and_default_limit(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = assigned(client)
    ok(browser, {"action": "start"})
    replay_all(client, clock, evaluate_each=False)
    everything = all_events(browser, contract)
    scanner = all_events(browser, contract, agentId="market-scanner")
    assert scanner == [e for e in everything if e["agentId"] == "market-scanner"]
    assert all_events(browser, contract, agentId="execution-monitor") == []
    # A cursor carries its filter.
    page = get_ok(browser, EVENTS, agentId="market-scanner", limit=1)
    assert page["nextCursor"] is not None
    assert browser.get(EVENTS, params={"cursor": page["nextCursor"]}).status_code == 400
    # More than the default page.
    db_rows(
        _db(),
        "INSERT INTO agent_events (user_id, agent_id, dedupe_key, reason_code, severity,"
        " message, data_as_of, created_at)"
        " SELECT user_id, 'market-scanner', 'filler:' || g, 'LARGE_MOVE', 'info', 'm',"
        " now(), now() FROM paper_accounts, generate_series(1, 30) g",
    )
    default = get_ok(browser, EVENTS)
    assert len(default["items"]) == 25 and default["nextCursor"] is not None
    assert len(get_ok(browser, EVENTS, limit=100)["items"]) == len(everything) + 30


def test_halt_cancel_stop_loss_and_reconciliation_events(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = assigned(client)
    ok(browser, {"action": "start"})
    # Replay until a buy is queued, then halt: the queued buy is cancelled.
    for _ in range(len(sessions("NSE:SBIN"))):
        tick(client)
        clock.advance(TICK)
        if db_rows(_db(), "SELECT 1 FROM paper_orders WHERE status = 'queued'"):
            break
    (order,) = db_rows(_db(), "SELECT id FROM paper_orders WHERE status = 'queued'")
    ok(browser, {"action": "halt", "confirmation": "STOP"})
    evaluate(client)
    items = all_events(browser, contract)
    codes = [e["reasonCode"] for e in items]
    assert "ENGINE_HALTED" in codes
    (cancel,) = [e for e in items if e["reasonCode"] == "ORDER_CANCELLED"]
    assert cancel["link"] == {"kind": "paper-order", "id": str(order["id"])}
    assert cancel["agentId"] == "execution-monitor"

    # A stop-loss fill appears in the ledger that the account does not
    # reflect: the risk explainer reports it and the monitor flags a mismatch.
    (row,) = db_rows(
        _db(),
        "INSERT INTO paper_trades (user_id, replay, instrument, side, quantity, fill_paise,"
        " fees_paise, pnl_paise, reason, filled_at, created_at)"
        " SELECT user_id, replay, 'SBIN', 'Sell', 3, 80000, 72, -1500, 'stop-loss', now(),"
        " now() FROM paper_accounts RETURNING id",
    )
    db_rows(_db(), "UPDATE paper_accounts SET updated_at = updated_at + interval '1 second'")
    evaluate(client)
    latest = get_ok(browser, EVENTS, limit=2)["items"]
    assert {e["reasonCode"] for e in latest} == {"STOP_LOSS_EXIT", "RECONCILIATION_MISMATCH"}
    stop = next(e for e in latest if e["reasonCode"] == "STOP_LOSS_EXIT")
    assert stop["link"] == {"kind": "paper-trade", "id": str(row["id"])}
    assert stop["severity"] == "warning" and stop["recommendation"]
    # The stray fill goes away: the ledger matches again.
    db_rows(_db(), "DELETE FROM paper_trades WHERE id = :id", id=row["id"])
    db_rows(_db(), "UPDATE paper_accounts SET updated_at = updated_at + interval '1 second'")
    evaluate(client)
    newest = get_ok(browser, EVENTS, limit=1)["items"][0]
    assert newest["reasonCode"] == "RECONCILIATION_MATCHED"
    # The deleted fill can no longer be verified, so its link is withheld.
    stop_again = next(
        e for e in all_events(browser, contract) if e["reasonCode"] == "STOP_LOSS_EXIT"
    )
    assert stop_again["link"] is None


# ---------------------------------------------------------- tenant isolation


def test_users_see_only_their_own_events_and_links(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    owner = assigned(client)
    ok(owner, {"action": "start"})
    replay_all(client, clock, evaluate_each=False)
    owner_events = all_events(owner, contract)
    assert owner_events

    other = Browser(client)
    other.login(phone=OTHER_PHONE)
    assert all_events(other, contract) == []
    assert state(health(other, contract))[2] == "NO_PAPER_ACTIVITY"
    # Another user's event id is not reachable through any filter.
    for agent_id in AGENT_IDS:
        assert all_events(other, contract, agentId=agent_id) == []

    # The other user gets a paper account of their own (replay 1 too), so the
    # owner's records below exist and differ from the reader's only in owner.
    (owner_id,) = [r["user_id"] for r in db_rows(_db(), "SELECT user_id FROM paper_accounts")]
    ok(other, {"action": "assign", "strategyId": active_strategy(other)})
    (other_id,) = [
        r["user_id"]
        for r in db_rows(
            _db(), "SELECT user_id FROM paper_accounts WHERE user_id <> :o", o=owner_id
        )
    ]
    trade_id = db_rows(_db(), "SELECT id FROM paper_trades WHERE user_id = :o LIMIT 1", o=owner_id)
    order_id = db_rows(_db(), "SELECT id FROM paper_orders WHERE user_id = :o LIMIT 1", o=owner_id)
    assert trade_id and order_id
    # An event of the other user that points at the owner's records keeps
    # its link hidden: the link must belong to the reader.
    for kind, link in (
        ("paper-trade", str(trade_id[0]["id"])),
        ("paper-order", str(order_id[0]["id"])),
        ("paper-order", str(uuid.uuid4())),
        ("paper-trade", "not-a-uuid"),
        ("paper-replay", "2"),
    ):
        db_rows(
            _db(),
            "INSERT INTO agent_events (user_id, agent_id, dedupe_key, reason_code, severity,"
            " message, link_kind, link_id, data_as_of, created_at)"
            " VALUES (:u, 'risk-explainer', :k, 'STOP_LOSS_EXIT', 'warning', 'm', :kind,"
            " :link, now(), now())",
            u=other_id,
            k=f"{kind}:{link}",
            kind=kind,
            link=link,
        )
    seen = all_events(other, contract)
    assert len(seen) == 5
    assert {e["link"] is None for e in seen} == {True}
    # The same kind of link to the reader's own replay is shown.
    db_rows(
        _db(),
        "INSERT INTO agent_events (user_id, agent_id, dedupe_key, reason_code, severity,"
        " message, link_kind, link_id, data_as_of, created_at)"
        " VALUES (:u, 'strategy-analyst', 'own', 'REPLAY_SUMMARY', 'info', 'm',"
        " 'paper-replay', '1', now(), now())",
        u=other_id,
    )
    newest = get_ok(other, EVENTS, limit=1)["items"][0]
    assert newest["link"] == {"kind": "paper-replay", "id": "1"}
    # The owner's view is unchanged.
    assert all_events(owner, contract) == owner_events


# --------------------------------------------------------- worker and database


def test_a_locked_user_is_skipped_and_ends_no_pass(client: TestClient) -> None:
    """While another worker holds one pending user (FOR UPDATE), a pass
    evaluates the other user without waiting, and records no pass end until
    the held user is evaluated too."""
    assigned(client)
    assigned(client, phone=OTHER_PHONE)
    db_rows(
        _db(),
        "INSERT INTO agent_runs (user_id, state) SELECT user_id, '{}'::jsonb FROM paper_accounts",
    )
    held, free = (r["user_id"] for r in db_rows(_db(), "SELECT user_id FROM agent_runs"))
    assert client.portal is not None
    service = agents(client)

    async def scenario() -> tuple[list[bool], list[Any], list[Any]]:
        import asyncio

        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(_db())
        try:
            async with engine.connect() as conn:
                await conn.begin()
                await conn.execute(
                    text("SELECT 1 FROM agent_runs WHERE user_id = :u FOR UPDATE"), {"u": held}
                )
                first = await asyncio.wait_for(service.run_once(), timeout=5)
                second = await asyncio.wait_for(service.run_once(), timeout=5)
                async with engine.connect() as peek:
                    runs = (
                        await peek.execute(
                            text("SELECT user_id, last_run_at FROM agent_runs ORDER BY 1")
                        )
                    ).all()
                    beat = (await peek.execute(text("SELECT * FROM agent_worker"))).all()
                await conn.rollback()  # release the lock
            return [first, second], list(runs), list(beat)
        finally:
            await engine.dispose()

    results, runs, beat = client.portal.call(scenario)
    assert results == [True, False]
    assert {r[0] for r in runs if r[1] is not None} == {free}
    assert beat == [], "a pass must not end while a pending user is held"
    # The lock is released: the held user is evaluated and the pass ends.
    assert evaluate(client) == 1
    assert db_rows(_db(), "SELECT 1 FROM agent_runs WHERE last_run_at IS NULL") == []
    assert db_rows(_db(), "SELECT pass_ended_at FROM agent_worker")


def test_the_background_worker_evaluates_changes(make_app: Callable[..., TestClient]) -> None:
    client = make_app(
        paper_worker_enabled=False,
        backtest_worker_enabled=False,
        agent_worker_poll_seconds=0.05,
    )
    browser = assigned(client)
    deadline = time.monotonic() + 10
    status = None
    pass_ended: list[dict[str, Any]] = []
    while time.monotonic() < deadline and (status != "ok" or not pass_ended):
        status = browser.get(HEALTH).json()["status"]
        pass_ended = db_rows(_db(), "SELECT pass_ended_at FROM agent_worker")
        time.sleep(0.05)
    assert status == "ok"
    assert pass_ended


def test_agent_events_are_append_only(client: TestClient, clock: FakeClock) -> None:
    browser = assigned(client)
    ok(browser, {"action": "halt", "confirmation": "STOP"})
    evaluate(client)
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError, match="append-only"):
        db_rows(_db(), "UPDATE agent_events SET message = 'edited'")
    with pytest.raises(DBAPIError):
        db_rows(_db(), "INSERT INTO agent_worker (id, pass_ended_at) VALUES (2, now())")
    # Deleting the user still cascades.
    db_rows(_db(), "DELETE FROM users")
    assert db_rows(_db(), "SELECT 1 FROM agent_events") == []
    assert db_rows(_db(), "SELECT 1 FROM agent_runs") == []


def test_agent_migration_rolls_back_and_forward(db_url: str) -> None:
    def present() -> set[str]:
        rows = db_rows(db_url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {r["tablename"] for r in rows}

    tables = {"agent_events", "agent_runs", "agent_worker", "paper_replay_finishes"}
    assert tables <= present()
    finished_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    try:
        command.downgrade(_alembic(db_url), "0007")
        assert not (tables & present())
        assert "paper_trades" in present()
        # One finished replay and one unfinished account: only the first is backfilled.
        for phone, replay, finished in (("+919000000101", 3, True), ("+919000000102", 2, False)):
            db_rows(
                db_url,
                "WITH u AS (INSERT INTO users (phone_e164, created_at, updated_at)"
                " VALUES (:phone, now(), now()) RETURNING id)"
                " INSERT INTO paper_accounts (user_id, engine, replay, capital_paise,"
                " cash_paise, position_quantity, position_fees_paise, sessions_done,"
                " sessions_total, finished, session_pnl_paise, session_fills,"
                " created_at, updated_at)"
                " SELECT id, 'idle', :replay, 100, 100, 0, 0, 0, 0, :finished, 0, 0,"
                " now(), :at FROM u RETURNING user_id",
                phone=phone,
                replay=replay,
                finished=finished,
                at=finished_at,
            )
        command.upgrade(_alembic(db_url), "head")
        backfilled = db_rows(
            db_url,
            "SELECT u.phone_e164, f.replay, f.finished_at FROM paper_replay_finishes f"
            " JOIN users u ON u.id = f.user_id",
        )
        assert backfilled == [
            {"phone_e164": "+919000000101", "replay": 3, "finished_at": finished_at}
        ]
    finally:
        command.upgrade(_alembic(db_url), "head")
        db_rows(db_url, "DELETE FROM users")
    assert tables <= present()


def test_every_contract_agent_operation_is_implemented(contract: Any, browser: Browser) -> None:
    served = browser.get("/openapi.json").json()["paths"]
    paths = [p for p in contract["paths"] if p.startswith("/api/v1/agents")]
    assert sorted(paths) == sorted([ROSTER, HEALTH, EVENTS])
    for path in paths:
        assert set(contract["paths"][path]) == {"get"}
        assert set(served[path]) == {"get"}, path


def test_strategy_commands_unaffected(browser: Browser) -> None:
    """Sanity: agents add no strategy or paper commands."""
    browser.login()
    response = browser.post(STRATEGY_COMMANDS, json={"action": "approve"})
    assert response.status_code == 400
    assert browser.post(PAPER_COMMANDS, json={"action": "agent"}).status_code == 400


def test_cursor_sequence_is_bounded_by_bigint(browser: Browser, contract: Any) -> None:
    browser.login()
    largest = get_ok(browser, EVENTS, cursor=encode_cursor(None, 2**63 - 1))
    assert largest["items"] == [] and largest["nextCursor"] is None
    response = browser.get(EVENTS, params={"cursor": encode_cursor(None, 2**63)})
    assert response.status_code == 400
    check(contract, "AgentError", response.json())


def test_a_replay_reassigned_before_evaluation_is_still_summarised(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = assigned(client)
    ok(browser, {"action": "start"})
    for _ in range(len(sessions("NSE:SBIN")) + 1):
        if not tick(client):
            break
        clock.advance(TICK)
    finishes = db_rows(_db(), "SELECT replay FROM paper_replay_finishes")
    assert finishes == [{"replay": 1}]
    # Reassign at once: the account now shows replay 2, unfinished.
    sid = db_rows(_db(), "SELECT strategy_id FROM paper_accounts")[0]["strategy_id"]
    ok(browser, {"action": "assign", "strategyId": str(sid)})
    assert db_rows(_db(), "SELECT replay, finished FROM paper_accounts") == [
        {"replay": 2, "finished": False}
    ]
    evaluate(client)
    summaries = [e for e in all_events(browser, contract) if e["reasonCode"] == "REPLAY_SUMMARY"]
    assert [e["link"] for e in summaries] == [{"kind": "paper-replay", "id": "1"}]
    trades = db_rows(_db(), "SELECT 1 FROM paper_trades WHERE replay = 1")
    assert f"{len(trades)} fill(s)" in summaries[0]["message"]
    # Evaluating again does not repeat it.
    db_rows(_db(), "UPDATE agent_runs SET data_as_of = NULL")
    evaluate(client)
    again = [e for e in all_events(browser, contract) if e["reasonCode"] == "REPLAY_SUMMARY"]
    assert len(again) == 1
