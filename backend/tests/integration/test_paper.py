"""Phase C3 paper trading endpoints and tick worker over real PostgreSQL and Redis.

Most tests run the app without its background worker and drive ticks with
`tick_once()` and the fake clock, so each replayed session is deterministic.
One test runs the real background worker end to end."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.demo import DemoMarketDataProvider
from app.paper import engine
from app.paper.models import PaperTrade
from app.paper.service import PaperService
from tests.support import OTHER_PHONE, Browser, FakeClock, db_rows

pytestmark = pytest.mark.integration

BASE = "/api/v1/auto-trading/paper"
COMMANDS = f"{BASE}/commands"
STRATEGIES = "/api/v1/strategies/preview"
STRATEGY_COMMANDS = f"{STRATEGIES}/commands"
CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"
BACKEND_DIR = Path(__file__).resolve().parents[2]
TICK = 3.0

PARAMS: dict[str, Any] = {
    "name": "SBIN Momentum",
    "description": "Daily momentum on SBIN.",
    "instrument": "SBIN",
    "timeframe": "1D",
    "riskTier": "medium",
    "positionSizeBps": 900,
    "stopLossBps": 125,
}


def _db() -> str:
    return os.environ["TEST_DATABASE_URL"]


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    # Both workers off: tests drive ticks and backtest runs themselves.
    return make_app(
        paper_worker_enabled=False, backtest_worker_enabled=False, paper_tick_seconds=TICK
    )


@pytest.fixture
def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


def check(contract: dict[str, Any], schema_name: str, payload: Any) -> None:
    schema = {"$ref": f"#/components/schemas/{schema_name}", "components": contract["components"]}
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    errors = list(validator.iter_errors(payload))
    assert not errors, [e.message for e in errors]


def service(client: TestClient) -> PaperService:
    paper: PaperService = client.app.state.paper  # type: ignore[attr-defined]
    return paper


def tick(client: TestClient) -> bool:
    assert client.portal is not None
    ticked: bool = client.portal.call(service(client).tick_once)
    return ticked


def send(browser: Browser, body: dict[str, Any], **kwargs: Any) -> Any:
    return browser.post(COMMANDS, json=body, **kwargs)


def ok(browser: Browser, body: dict[str, Any]) -> dict[str, Any]:
    response = send(browser, body)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


def active_strategy(browser: Browser, **overrides: Any) -> str:
    """Create a strategy, mark its checks passed and activate it (version 1)."""
    response = browser.post(
        STRATEGY_COMMANDS, json={"action": "create", "parameters": {**PARAMS, **overrides}}
    )
    assert response.status_code == 200, response.text
    sid: str = response.json()["strategies"][-1]["id"]
    db_rows(
        _db(),
        "UPDATE strategies SET draft_backtest = 'passed', draft_risk_review = 'approved'"
        " WHERE id = :id",
        id=sid,
    )
    response = browser.post(STRATEGY_COMMANDS, json={"action": "activate", "id": sid})
    assert response.status_code == 200, response.text
    return sid


def sessions(instrument_id: str) -> list[engine.Session]:
    candles = asyncio.run(DemoMarketDataProvider().get_candles(instrument_id, "1D"))
    assert candles is not None
    return [engine.Session(c.time, c.open, c.low, c.close) for c in candles.candles]


def expected_replay(
    instrument_id: str, size_bps: int, stop_bps: int
) -> tuple[engine.State, list[engine.Fill]]:
    bars = sessions(instrument_id)
    state = engine.State(cash_paise=engine.CAPITAL_PAISE)
    fills: list[engine.Fill] = []
    queued: engine.QueuedOrder | None = None
    for _ in range(len(bars)):
        if state.sessions_done == len(bars):
            break
        out = engine.step(
            state, bars, queued, size_bps=size_bps, stop_loss_bps=stop_bps, symbol="X"
        )
        fills.extend(out.fills)
        queued = None
        if out.new_order is not None:
            queued = engine.QueuedOrder(out.new_order.side, out.new_order.quantity)
    assert state.sessions_done == len(bars), "the engine did not advance one session per step"
    return state, fills


def run_to_end(client: TestClient, clock: FakeClock) -> int:
    """Tick until the replay finishes, at most one tick per demo session."""
    budget = len(sessions("NSE:SBIN"))
    ticks = 0
    while ticks < budget and tick(client):
        ticks += 1
        clock.advance(TICK)
    clock.advance(TICK)
    assert not tick(client), "a tick is still due after every session was replayed"
    return ticks


# ------------------------------------------------------------------ auth and CSRF


def test_requires_a_session(browser: Browser, contract: Any) -> None:
    response = browser.get(BASE)
    assert response.status_code == 401
    check(contract, "PaperError", response.json())
    browser.get_csrf()
    response = send(browser, {"action": "start"})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_commands_require_session_csrf_token(browser: Browser, contract: Any) -> None:
    browser.login()
    response = send(
        browser, {"action": "halt", "confirmation": "STOP"}, headers=browser.headers(csrf="")
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    check(contract, "PaperError", response.json())
    assert db_rows(_db(), "SELECT 1 FROM paper_accounts") == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"action": "launch"},
        {"action": "halt"},
        {"action": "halt", "confirmation": "stop"},
        {"action": "assign"},
        {"action": "assign", "strategyId": ""},
        {"action": "assign", "strategyId": "x" * 65},
        {"action": "start", "extra": 1},
    ],
)
def test_malformed_commands_are_400(browser: Browser, contract: Any, body: Any) -> None:
    browser.login()
    response = send(browser, body)
    assert response.status_code == 400
    check(contract, "PaperError", response.json())
    assert response.json()["code"] == "INVALID_REQUEST"


# ---------------------------------------------------------------------- workspace


def test_new_user_workspace_is_empty(browser: Browser, contract: Any) -> None:
    browser.login()
    response = browser.get(BASE)
    assert response.status_code == 200
    assert response.json() == {"status": "empty"}
    check(contract, "PaperResult", response.json())


def test_active_strategy_makes_a_ready_idle_workspace(
    browser: Browser, clock: FakeClock, contract: Any
) -> None:
    browser.login()
    sid = active_strategy(browser)
    active_strategy(browser, name="Second strategy")
    # Draft-only strategies are not listed.
    browser.post(STRATEGY_COMMANDS, json={"action": "create", "parameters": PARAMS})
    body = browser.get(BASE).json()
    check(contract, "PaperResult", body)
    data = body["data"]
    assert body["status"] == "ready"
    assert data["asOf"].startswith(clock.now.strftime("%Y-%m-%dT%H:%M"))
    assert (data["source"], data["environment"], data["engine"]) == ("demo", "PAPER", "idle")
    assert data["strategyId"] is None
    assert data["agent"] == {"name": "Paper execution agent", "ready": False}
    assert (data["strategies"][0]["id"], data["strategies"][0]["version"]) == (sid, 1)
    assert [s["name"] for s in data["strategies"]] == ["SBIN Momentum", "Second strategy"]
    assert data["risk"] == {
        "status": "approved",
        "dailyLossPaise": 0,
        "lossLimitPaise": 2_500_000,
        "tradesToday": 0,
        "tradeLimit": 10,
    }
    assert data["account"] == {
        "capitalPaise": 100_000_000,
        "cashPaise": 100_000_000,
        "equityPaise": 100_000_000,
        "positionQuantity": 0,
        "perTradeRiskPaise": 1_000_000,
    }
    assert data["replay"] == {
        "sessionDate": None,
        "sessionsDone": 0,
        "sessionsTotal": 0,
        "finished": False,
    }
    assert (data["orders"], data["trades"], data["events"]) == ([], [], [])


# ----------------------------------------------------------------------- commands


def test_assign_rules(client: TestClient, contract: Any) -> None:
    owner, other = Browser(client), Browser(client)
    owner.login()
    other.login(phone=OTHER_PHONE)
    sid = active_strategy(owner)
    draft = owner.post(STRATEGY_COMMANDS, json={"action": "create", "parameters": PARAMS})
    draft_id = draft.json()["strategies"][-1]["id"]
    for bad in (str(uuid.uuid4()), "not-a-uuid", draft_id):
        response = send(owner, {"action": "assign", "strategyId": bad})
        assert response.status_code == 409, bad
        check(contract, "PaperError", response.json())
        assert response.json()["code"] == "PAPER_CONFLICT"
    # Another user's strategy cannot be assigned.
    response = send(other, {"action": "assign", "strategyId": sid})
    assert response.status_code == 409

    data = ok(owner, {"action": "assign", "strategyId": sid})
    check(contract, "PaperSnapshot", data)
    assert data["strategyId"] == sid and data["engine"] == "idle"
    assert data["agent"]["ready"] is True
    assert data["replay"] == {
        "sessionDate": None,
        "sessionsDone": 0,
        "sessionsTotal": len(sessions("NSE:SBIN")),
        "finished": False,
    }
    assert [e["message"] for e in data["events"]] == [
        "Assigned SBIN Momentum v1 for a paper replay of SBIN."
    ]
    # Assigning it again while its replay can continue changes nothing.
    again = ok(owner, {"action": "assign", "strategyId": sid})
    assert len(again["events"]) == 1
    audit = db_rows(_db(), "SELECT action FROM audit_events WHERE action LIKE 'paper.%'")
    assert [a["action"] for a in audit] == ["paper.assign"]


def test_engine_state_machine(browser: Browser, contract: Any) -> None:
    browser.login()
    sid = active_strategy(browser)

    def conflict(body: dict[str, Any]) -> None:
        response = send(browser, body)
        assert response.status_code == 409, (body, response.text)
        assert response.json()["code"] == "PAPER_CONFLICT"

    conflict({"action": "start"})  # nothing assigned
    conflict({"action": "pause"})
    conflict({"action": "reset"})
    ok(browser, {"action": "assign", "strategyId": sid})
    assert ok(browser, {"action": "start"})["engine"] == "running"
    conflict({"action": "start"})
    conflict({"action": "assign", "strategyId": sid})
    conflict({"action": "reset"})
    assert ok(browser, {"action": "pause"})["engine"] == "idle"
    assert ok(browser, {"action": "start"})["engine"] == "running"
    halted = ok(browser, {"action": "halt", "confirmation": "STOP"})
    check(contract, "PaperSnapshot", halted)
    assert halted["engine"] == "halted" and halted["risk"]["status"] == "blocked"
    conflict({"action": "halt", "confirmation": "STOP"})
    conflict({"action": "start"})
    conflict({"action": "pause"})
    conflict({"action": "assign", "strategyId": sid})
    reset = ok(browser, {"action": "reset"})
    assert reset["engine"] == "idle" and reset["risk"]["status"] == "approved"
    assert [e["message"] for e in reset["events"]] == [
        "Assigned SBIN Momentum v1 for a paper replay of SBIN.",
        "Paper engine started.",
        "Paper engine paused.",
        "Paper engine started.",
        "Kill switch: engine halted and 0 queued order(s) cancelled.",
        "Paper engine reset after a halt. It is idle.",
    ]


def test_halt_needs_no_assignment(browser: Browser) -> None:
    browser.login()
    data = ok(browser, {"action": "halt", "confirmation": "STOP"})
    assert data["engine"] == "halted" and data["strategyId"] is None
    # Never assigned and no active strategy: the workspace is still empty.
    assert browser.get(BASE).json() == {"status": "empty"}


# ------------------------------------------------------------------------ replay


def test_full_replay_matches_the_engine(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = Browser(client)
    browser.login()
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    assert not tick(client)  # idle: nothing to do
    ok(browser, {"action": "start"})
    assert tick(client)
    assert not tick(client)  # not due again until the tick interval passes
    clock.advance(TICK)
    assert tick(client)
    mid = browser.get(BASE).json()["data"]
    assert mid["replay"]["sessionsDone"] == 2
    assert mid["replay"]["sessionDate"] == sessions("NSE:SBIN")[1].time.date().isoformat()

    clock.advance(TICK)
    run_to_end(client, clock)
    body = browser.get(BASE).json()
    check(contract, "PaperResult", body)
    data = body["data"]
    state, fills = expected_replay("NSE:SBIN", 900, 125)
    total = len(sessions("NSE:SBIN"))
    assert data["engine"] == "idle" and data["agent"]["ready"] is False
    assert data["replay"]["finished"] is True and data["replay"]["sessionsDone"] == total
    assert data["account"]["cashPaise"] == state.cash_paise
    assert data["account"]["equityPaise"] == state.cash_paise
    assert data["account"]["positionQuantity"] == 0
    assert fills, "the demo replay should trade"
    got = [
        (t["side"], t["quantity"], t["fillPaise"], t["feesPaise"], t["pnlPaise"], t["reason"])
        for t in reversed(data["trades"])
    ]
    assert got == [
        (f.side, f.quantity, f.fill_paise, f.fees_paise, f.pnl_paise, f.reason) for f in fills
    ]
    assert all(o["status"] in ("filled", "cancelled") for o in data["orders"])
    assert all(o["approval"] == "approved" for o in data["orders"])
    assert data["events"][-1]["message"] == "Replay finished. The engine is idle."
    # A finished replay cannot start; assigning again starts a fresh one.
    assert send(browser, {"action": "start"}).status_code == 409
    fresh = ok(browser, {"action": "assign", "strategyId": sid})
    assert (fresh["orders"], fresh["trades"]) == ([], [])
    assert fresh["account"]["cashPaise"] == engine.CAPITAL_PAISE
    assert fresh["replay"]["sessionsDone"] == 0 and fresh["replay"]["finished"] is False
    # The ledger keeps the earlier replay's rows.
    assert len(db_rows(_db(), "SELECT 1 FROM paper_trades")) == len(fills)


def test_halt_cancels_queued_orders(client: TestClient, clock: FakeClock) -> None:
    browser = Browser(client)
    browser.login()
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    ok(browser, {"action": "start"})
    queued: list[dict[str, Any]] = []
    while not queued:
        assert tick(client), "expected the replay to queue an order"
        clock.advance(TICK)
        queued = [o for o in browser.get(BASE).json()["data"]["orders"] if o["status"] == "queued"]
    data = ok(browser, {"action": "halt", "confirmation": "STOP"})
    assert [o["status"] for o in data["orders"] if o["id"] == queued[0]["id"]] == ["cancelled"]
    assert (
        data["events"][-1]["message"]
        == "Kill switch: engine halted and 1 queued order(s) cancelled."
    )
    assert not tick(client)  # a halted engine is not ticked


def test_paused_strategy_stops_the_engine(client: TestClient) -> None:
    browser = Browser(client)
    browser.login()
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    ok(browser, {"action": "start"})
    browser.post(STRATEGY_COMMANDS, json={"action": "pause", "id": sid})
    assert tick(client)
    data = browser.get(BASE).json()["data"]
    assert data["engine"] == "idle" and data["replay"]["sessionsDone"] == 0
    assert data["events"][-1]["message"] == (
        "The assigned strategy is no longer active. Engine paused."
    )
    assert data["strategies"] == [] and data["agent"]["ready"] is False
    response = send(browser, {"action": "start"})
    assert response.status_code == 409


def test_assigned_strategy_keeps_its_pinned_version(client: TestClient, clock: FakeClock) -> None:
    browser = Browser(client)
    browser.login()
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    # A new version (v2) with smaller sizing is activated after assignment.
    browser.post(STRATEGY_COMMANDS, json={"action": "pause", "id": sid})
    browser.post(
        STRATEGY_COMMANDS,
        json={"action": "save-draft", "id": sid, "parameters": {**PARAMS, "positionSizeBps": 500}},
    )
    db_rows(_db(), "UPDATE strategies SET draft_backtest = 'passed' WHERE id = :id", id=sid)
    assert (
        browser.post(STRATEGY_COMMANDS, json={"action": "activate", "id": sid}).status_code == 200
    )
    data = browser.get(BASE).json()["data"]
    assert [(s["id"], s["version"]) for s in data["strategies"]] == [(sid, 1)]
    (row,) = db_rows(_db(), "SELECT version_number, version_parameters FROM paper_accounts")
    assert row["version_number"] == 1
    assert row["version_parameters"]["position_size_bps"] == 900

    # The replay sizes its orders with the pinned 900 bps, not v2's 500 bps.
    ok(browser, {"action": "start"})
    buys: list[dict[str, Any]] = []
    for _ in range(len(sessions("NSE:SBIN"))):
        if buys or not tick(client):
            break
        clock.advance(TICK)
        buys = [o for o in browser.get(BASE).json()["data"]["orders"] if o["side"] == "Buy"]
    assert buys, "expected the replay to queue a buy"
    (buy,) = buys
    cash = engine.CAPITAL_PAISE
    pinned = engine.buy_quantity(cash, buy["limitPaise"], 900, 125)
    assert pinned != engine.buy_quantity(cash, buy["limitPaise"], 500, 125)
    assert buy["quantity"] == pinned


def test_contending_workers_replay_a_session_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker skips an account another worker holds (SKIP LOCKED)."""
    browser = Browser(client)
    browser.login()
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    ok(browser, {"action": "start"})
    paper = service(client)
    real_replay = paper._replay_session
    results: list[bool] = []

    async def both() -> None:
        locked, release = asyncio.Event(), asyncio.Event()

        async def held(*args: Any, **kwargs: Any) -> None:
            locked.set()  # the first worker now holds the account row lock
            await release.wait()
            await real_replay(*args, **kwargs)

        monkeypatch.setattr(paper, "_replay_session", held)
        first = asyncio.create_task(paper.tick_once())
        try:
            await asyncio.wait_for(locked.wait(), timeout=5)
            # Without SKIP LOCKED this call would block on the row and time out.
            second = await asyncio.wait_for(paper.tick_once(), timeout=5)
        finally:
            release.set()
        results.extend([await first, second])

    assert client.portal is not None
    client.portal.call(both)
    assert results == [True, False]
    (row,) = db_rows(_db(), "SELECT sessions_done FROM paper_accounts")
    assert row["sessions_done"] == 1


def test_failed_tick_leaves_no_partial_ledger(
    client: TestClient, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = Browser(client)
    browser.login()
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    ok(browser, {"action": "start"})
    # Advance until the next session will fill a queued order.
    for _ in range(len(sessions("NSE:SBIN"))):
        queued = db_rows(_db(), "SELECT 1 FROM paper_orders WHERE status = 'queued'")
        if queued:
            break
        assert tick(client)
        clock.advance(TICK)
    assert queued, "expected a queued order"

    def snapshot() -> tuple[Any, ...]:
        account = db_rows(_db(), "SELECT sessions_done, cash_paise FROM paper_accounts")
        counts = [
            len(db_rows(_db(), f"SELECT 1 FROM {t}"))
            for t in ("paper_trades", "paper_events", "paper_orders")
        ]
        statuses = db_rows(_db(), "SELECT status FROM paper_orders ORDER BY seq")
        return (account, counts, statuses)

    before = snapshot()
    paper = service(client)
    real_replay = paper._replay_session
    staged: list[int] = []

    async def failing_replay(
        db: AsyncSession, account: Any, symbols: dict[str, str], now: datetime
    ) -> None:
        await real_replay(db, account, symbols, now)
        await db.flush()  # the ledger rows reach the database inside the transaction
        staged.append(await db.scalar(select(func.count()).select_from(PaperTrade)) or 0)
        raise RuntimeError("replay failed after staging ledger writes")

    monkeypatch.setattr(paper, "_replay_session", failing_replay)
    with pytest.raises(RuntimeError):
        tick(client)
    assert len(staged) == 1 and staged[0] > before[1][0], "expected a staged fill"
    assert snapshot() == before
    monkeypatch.setattr(paper, "_replay_session", real_replay)
    assert tick(client)
    after = snapshot()
    assert after[0][0]["sessions_done"] == before[0][0]["sessions_done"] + 1
    assert after[1][0] > before[1][0]  # the retried session filled the order


def test_users_are_isolated(client: TestClient, clock: FakeClock) -> None:
    first, second = Browser(client), Browser(client)
    first.login()
    second.login(phone=OTHER_PHONE)
    sid = active_strategy(first)
    ok(first, {"action": "assign", "strategyId": sid})
    ok(first, {"action": "start"})
    assert tick(client)
    assert second.get(BASE).json() == {"status": "empty"}
    data = ok(second, {"action": "halt", "confirmation": "STOP"})
    assert data["events"][-1]["message"].startswith("Kill switch")
    assert all("Assigned" not in e["message"] for e in data["events"])
    assert first.get(BASE).json()["data"]["engine"] == "running"


def test_disabled_is_503(make_app: Callable[..., TestClient], contract: Any) -> None:
    browser = Browser(make_app(paper_enabled=False))
    browser.login()
    for response in (browser.get(BASE), send(browser, {"action": "start"})):
        assert response.status_code == 503
        check(contract, "PaperError", response.json())
        assert response.json()["code"] == "PAPER_UNAVAILABLE"


# ------------------------------------------------------------------ worker task


def test_background_worker_replays_sessions(make_app: Callable[..., TestClient]) -> None:
    browser = Browser(make_app(paper_tick_seconds=0.5, paper_worker_poll_seconds=0.1))
    browser.login()
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    ok(browser, {"action": "start"})
    # The fake clock does not move, so the worker replays the first session
    # (due at once) and then waits for the tick interval.
    deadline = time.monotonic() + 10
    done = 0
    while time.monotonic() < deadline and done < 1:
        done = browser.get(BASE).json()["data"]["replay"]["sessionsDone"]
        time.sleep(0.05)
    assert done == 1


# ---------------------------------------------------------------------- database


def test_every_contract_paper_operation_is_implemented(contract: Any, browser: Browser) -> None:
    served = browser.get("/openapi.json").json()["paths"]
    paths = [p for p in contract["paths"] if p.startswith("/api/v1/auto-trading/")]
    assert len(paths) == 2
    for path in paths:
        assert path in served, f"{path} missing from the API"
        for method in contract["paths"][path]:
            assert method in served[path], f"{method.upper()} {path} missing"


def test_ledger_is_append_only_and_cascades(client: TestClient, clock: FakeClock) -> None:
    browser = Browser(client)
    browser.login()
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    ok(browser, {"action": "start"})
    run_to_end(client, clock)
    with pytest.raises(Exception, match="append-only"):
        db_rows(_db(), "UPDATE paper_events SET message = 'x'")
    with pytest.raises(Exception, match="append-only"):
        db_rows(_db(), "UPDATE paper_trades SET pnl_paise = 0")
    with pytest.raises(Exception, match="running_unfinished"):
        db_rows(_db(), "UPDATE paper_accounts SET engine = 'running'")
    with pytest.raises(Exception, match="cash_nonnegative"):
        db_rows(_db(), "UPDATE paper_accounts SET cash_paise = -1")
    db_rows(_db(), "DELETE FROM users")
    for table in ("paper_accounts", "paper_orders", "paper_trades", "paper_events"):
        assert db_rows(_db(), f"SELECT 1 FROM {table}") == [], table


def _alembic(db_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = db_url
    return cfg


def test_paper_migration_rolls_back_and_forward(db_url: str) -> None:
    def present() -> set[str]:
        rows = db_rows(db_url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {r["tablename"] for r in rows}

    tables = {"paper_accounts", "paper_orders", "paper_trades", "paper_events"}
    assert tables <= present()
    command.downgrade(_alembic(db_url), "0005")
    assert not (tables & present())
    assert db_rows(db_url, "SELECT 1 FROM pg_proc WHERE proname = 'paper_ledger_append_only'") == []
    command.upgrade(_alembic(db_url), "head")
    assert tables <= present()


def test_migration_reevaluates_existing_drafts(client: TestClient, db_url: str) -> None:
    """Drafts written before 0006 (unavailable/pending) get the automatic checks."""
    browser = Browser(client)
    browser.login()

    def strategy(**overrides: Any) -> str:
        response = browser.post(
            STRATEGY_COMMANDS,
            json={
                "action": "create",
                "parameters": {**PARAMS, "instrument": "NIFTY 50", **overrides},
            },
        )
        sid: str = response.json()["strategies"][-1]["id"]
        return sid

    passing, rejected, unrun, edited = (
        strategy(),
        strategy(positionSizeBps=1001),
        strategy(),
        strategy(),
    )
    window = {
        "instrumentId": "NSE:NIFTY50",
        "from": "2026-10-05",
        "to": "2026-11-23",
        "outOfSampleFrom": "2026-10-21",
        "capitalPaise": 50_000_000,
        "feeBps": 8,
        "slippageBps": 5,
    }
    backtests = client.app.state.backtests  # type: ignore[attr-defined]
    for sid in (passing, edited):
        response = browser.post(
            "/api/v1/backtests/preview/runs", json={**window, "strategyId": f"{sid}:draft"}
        )
        assert response.status_code == 202, response.text
        assert client.portal is not None
        assert client.portal.call(backtests.process_next)
    db_rows(
        db_url,
        "UPDATE strategies SET draft_parameters = jsonb_set(draft_parameters,"
        " '{stop_loss_bps}', '150') WHERE id = :id",
        id=edited,
    )
    command.downgrade(_alembic(db_url), "0005")
    rows = db_rows(db_url, "SELECT DISTINCT draft_backtest, draft_risk_review FROM strategies")
    assert rows == [{"draft_backtest": "unavailable", "draft_risk_review": "pending"}]
    command.upgrade(_alembic(db_url), "head")
    checks = {
        r["id"]: (r["draft_backtest"], r["draft_risk_review"])
        for r in db_rows(
            db_url, "SELECT id::text, draft_backtest, draft_risk_review FROM strategies"
        )
    }
    assert checks == {
        passing: ("passed", "approved"),
        rejected: ("unavailable", "rejected"),
        unrun: ("unavailable", "approved"),
        edited: ("unavailable", "approved"),
    }
