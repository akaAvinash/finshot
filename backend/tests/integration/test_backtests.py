"""Phase C2 backtest endpoints and worker over real PostgreSQL and Redis.

Most tests run the app without its background worker and drive the worker
with `process_next()`, so each step is deterministic. One test runs the real
background worker end to end."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from app.backtests.engine import Bar, Window, replay
from app.backtests.service import (
    INVALID_DATES,
    OUT_OF_ORDER,
    OUTSIDE_HISTORY,
    RUN_ABANDONED,
    RUN_FAILED,
    UNKNOWN_INPUT,
    BacktestService,
)
from app.market.demo import DemoMarketDataProvider
from app.strategies.rules import backtest_verdict
from app.strategies.schemas import StrategyParameters
from tests.support import OTHER_PHONE, Browser, FakeClock, db_rows

pytestmark = pytest.mark.integration

BASE = "/api/v1/backtests/preview"
RUNS = f"{BASE}/runs"
STRATEGY_COMMANDS = "/api/v1/strategies/preview/commands"
CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"
BACKEND_DIR = Path(__file__).resolve().parents[2]

PARAMS: dict[str, Any] = {
    "name": "NIFTY Momentum",
    "description": "Intraday breakouts with confirmation from the trend.",
    "instrument": "NIFTY 50",
    "timeframe": "15m",
    "riskTier": "medium",
    "positionSizeBps": 900,
    "stopLossBps": 125,
}
TOO_FEW = "Choose at least three warm-up sessions and two out-of-sample sessions."


def _db() -> str:
    return os.environ["TEST_DATABASE_URL"]


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    return make_app(backtest_worker_enabled=False)


@pytest.fixture
def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


def check(contract: dict[str, Any], schema_name: str, payload: Any) -> None:
    validate(contract, {"$ref": f"#/components/schemas/{schema_name}"}, payload)


def check_queued(contract: dict[str, Any], payload: Any) -> None:
    """The POST's own 202 schema, which only allows status `queued`."""
    responses = contract["paths"][RUNS]["post"]["responses"]
    validate(contract, responses["202"]["content"]["application/json"]["schema"], payload)


def validate(contract: dict[str, Any], schema: dict[str, Any], payload: Any) -> None:
    schema = {**schema, "components": contract["components"]}
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    errors = list(validator.iter_errors(payload))
    assert not errors, [e.message for e in errors]


def service(client: TestClient) -> BacktestService:
    backtests: BacktestService = client.app.state.backtests  # type: ignore[attr-defined]
    return backtests


def work(client: TestClient) -> bool:
    """Let the worker finish the oldest queued run."""
    assert client.portal is not None
    processed: bool = client.portal.call(service(client).process_next)
    return processed


def create_strategy(browser: Browser, **overrides: Any) -> str:
    response = browser.post(
        STRATEGY_COMMANDS, json={"action": "create", "parameters": {**PARAMS, **overrides}}
    )
    assert response.status_code == 200, response.text
    strategy_id: str = response.json()["strategies"][-1]["id"]
    return strategy_id


def save_draft(browser: Browser, strategy_id: str, **overrides: Any) -> None:
    response = browser.post(
        STRATEGY_COMMANDS,
        json={"action": "save-draft", "id": strategy_id, "parameters": {**PARAMS, **overrides}},
    )
    assert response.status_code == 200, response.text


def activate(browser: Browser, strategy_id: str) -> None:
    # Mark the checks directly so tests do not depend on a passing run.
    db_rows(
        _db(),
        "UPDATE strategies SET draft_backtest = 'passed', draft_risk_review = 'approved'"
        " WHERE id = :id",
        id=strategy_id,
    )
    response = browser.post(STRATEGY_COMMANDS, json={"action": "activate", "id": strategy_id})
    assert response.status_code == 200, response.text


def config(strategy_ref: str, **overrides: Any) -> dict[str, Any]:
    return {
        "strategyId": strategy_ref,
        "instrumentId": "NSE:NIFTY50",
        "from": "2026-10-05",
        "to": "2026-11-23",
        "outOfSampleFrom": "2026-10-21",
        "capitalPaise": 50_000_000,
        "feeBps": 8,
        "slippageBps": 5,
        **overrides,
    }


def start(browser: Browser, body: dict[str, Any], **kwargs: Any) -> Any:
    return browser.post(RUNS, json=body, **kwargs)


def draft_ref(browser: Browser) -> str:
    """Log in (if needed), create a strategy and return its draft's revision id."""
    if browser.csrf is None:
        browser.login_ready()
    sid = create_strategy(browser)
    return f"{sid}:draft"


def expected_result(body: dict[str, Any], position_size_bps: int) -> dict[str, Any]:
    candles = asyncio.run(DemoMarketDataProvider().get_candles(body["instrumentId"], "1D"))
    assert candles is not None
    window = Window(
        start=date.fromisoformat(body["from"]),
        end=date.fromisoformat(body["to"]),
        out_of_sample_from=date.fromisoformat(body["outOfSampleFrom"]),
        capital_paise=body["capitalPaise"],
        fee_bps=body["feeBps"],
        slippage_bps=body["slippageBps"],
    )
    bars = [Bar(c.time, c.open, c.close) for c in candles.candles]
    return replay(window, bars, position_size_bps)


def run_count() -> int:
    count: int = db_rows(_db(), "SELECT count(*) AS n FROM backtest_runs")[0]["n"]
    return count


# ------------------------------------------------------------------ auth and CSRF


def test_requires_a_session(browser: Browser, contract: Any) -> None:
    for response in (browser.get(BASE), browser.get(f"{RUNS}/{uuid.uuid4()}")):
        assert response.status_code == 401
        check(contract, "BacktestError", response.json())
    browser.get_csrf()
    response = start(browser, config(f"{uuid.uuid4()}:draft"))
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_start_requires_session_csrf_token(browser: Browser, contract: Any) -> None:
    ref = draft_ref(browser)
    response = start(browser, config(ref), headers=browser.headers(csrf=""))
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    check(contract, "BacktestError", response.json())
    assert run_count() == 0


# ---------------------------------------------------------------------- workspace


def test_new_user_workspace(browser: Browser, clock: FakeClock, contract: Any) -> None:
    browser.login_ready()
    body = browser.get(BASE).json()
    check(contract, "BacktestWorkspaceResult", body)
    data = body["data"]
    assert body["status"] == "ready"
    assert (data["source"], data["environment"]) == ("demo", "DEMO")
    assert (data["from"], data["to"]) == ("2026-10-01", "2026-11-23")
    assert data["strategies"] == [] and data["runs"] == []
    assert {"id": "NSE:NIFTY50", "symbol": "NIFTY 50"} in data["instruments"]
    assert parse(data["asOf"]) == clock.now


def test_workspace_lists_each_version_and_the_draft(browser: Browser, contract: Any) -> None:
    browser.login_ready()
    sid = create_strategy(browser)
    activate(browser, sid)
    save_draft(browser, sid, name="NIFTY Momentum v2", positionSizeBps=750, instrument="SBIN")
    other = create_strategy(browser, name="Bank range", instrument="BANKNIFTY")
    body = browser.get(BASE).json()
    check(contract, "BacktestWorkspaceResult", body)
    assert body["data"]["strategies"] == [
        {
            "id": f"{sid}:1",
            "name": "NIFTY Momentum",
            "revision": 1,
            "instrumentId": "NSE:NIFTY50",
            "positionSizeBps": 900,
        },
        {
            "id": f"{sid}:draft",
            "name": "NIFTY Momentum v2",
            "revision": "draft",
            "instrumentId": "NSE:SBIN",
            "positionSizeBps": 750,
        },
        {
            "id": f"{other}:draft",
            "name": "Bank range",
            "revision": "draft",
            "instrumentId": "NSE:BANKNIFTY",
            "positionSizeBps": 900,
        },
    ]


# ---------------------------------------------------------------------- lifecycle


def test_run_lifecycle(client: TestClient, clock: FakeClock, contract: Any) -> None:
    browser = Browser(client)
    browser.login_ready()
    sid = create_strategy(browser)
    activate(browser, sid)
    body = config(f"{sid}:1")

    response = start(browser, body)
    assert response.status_code == 202, response.text
    queued = response.json()
    check_queued(contract, queued)
    assert queued["status"] == "queued"
    assert queued["config"] == body
    assert parse(queued["queuedAt"]) == parse(queued["asOf"]) == clock.now
    assert "result" not in queued and "message" not in queued
    assert browser.get(f"{RUNS}/{queued['id']}").json() == queued

    clock.advance(30)
    assert work(client) is True
    assert work(client) is False
    done = browser.get(f"{RUNS}/{queued['id']}").json()
    check(contract, "BacktestRun", done)
    assert done["status"] == "completed"
    assert parse(done["asOf"]) == clock.now
    assert parse(done["queuedAt"]) == parse(queued["queuedAt"])
    assert done["result"] == expected_result(body, 900)

    workspace = browser.get(BASE).json()
    check(contract, "BacktestWorkspaceResult", workspace)
    assert workspace["data"]["runs"] == [done]

    audit = db_rows(
        _db(), "SELECT action, resource FROM audit_events WHERE action LIKE 'backtest.%'"
    )
    assert audit == [{"action": "backtest.queue", "resource": f"backtest:{queued['id']}"}]


def test_queued_schema_rejects_other_statuses(contract: Any) -> None:
    running = {
        "id": "r",
        "source": "demo",
        "environment": "DEMO",
        "asOf": "2026-11-24T06:00:00Z",
        "queuedAt": "2026-11-24T06:00:00Z",
        "config": config(f"{uuid.uuid4()}:draft"),
        "status": "running",
    }
    check(contract, "BacktestRun", running)
    with pytest.raises(AssertionError):
        check_queued(contract, running)


def test_request_instrument_chooses_the_candles(client: TestClient) -> None:
    """The revision supplies only its position size; the request picks the candles."""
    browser = Browser(client)
    ref = draft_ref(browser)  # a NIFTY 50 strategy with positionSizeBps 900
    body = config(ref, instrumentId="NSE:SBIN")
    run_id = start(browser, body).json()["id"]
    assert work(client)
    result = browser.get(f"{RUNS}/{run_id}").json()["result"]
    assert result == expected_result(body, 900)
    assert result != expected_result(config(ref), 900)


def draft_check(browser: Browser, sid: str) -> str:
    strategies = browser.get("/api/v1/strategies/preview").json()["data"]["strategies"]
    (strategy,) = [s for s in strategies if s["id"] == sid]
    check: str = strategy["draft"]["backtest"]
    return check


# A window with 25 out-of-sample sessions, and one with only 8.
LONG_WINDOW: dict[str, Any] = {}
SHORT_WINDOW: dict[str, Any] = {"from": "2026-10-20", "outOfSampleFrom": "2026-11-12"}


def test_completed_draft_run_sets_the_strategy_check(client: TestClient) -> None:
    browser = Browser(client)
    browser.login_ready()
    sid = create_strategy(browser)
    body = config(f"{sid}:draft", **LONG_WINDOW)
    expected = backtest_verdict(
        StrategyParameters.model_validate(PARAMS), expected_result(body, 900)
    )
    assert expected == "passed"  # this demo window passes the medium-tier rule
    run_id = start(browser, body).json()["id"]
    assert draft_check(browser, sid) == "unavailable"  # queued: unchanged
    assert work(client)
    assert browser.get(f"{RUNS}/{run_id}").json()["status"] == "completed"
    assert draft_check(browser, sid) == "passed"
    audit = db_rows(
        _db(), "SELECT actor, action, resource FROM audit_events WHERE action LIKE 'strategy.back%'"
    )
    assert audit == [
        {
            "actor": "system:backtest-worker",
            "action": "strategy.backtest_passed",
            "resource": f"strategy:{sid}",
        }
    ]
    # The draft can now be activated.
    response = browser.post(STRATEGY_COMMANDS, json={"action": "activate", "id": sid})
    assert response.status_code == 200, response.text


def test_failing_draft_run_fails_the_check_and_the_latest_run_wins(client: TestClient) -> None:
    browser = Browser(client)
    browser.login_ready()
    sid = create_strategy(browser)
    short = config(f"{sid}:draft", **SHORT_WINDOW)
    result = expected_result(short, 900)
    assert len(result["points"]) < 10
    assert backtest_verdict(StrategyParameters.model_validate(PARAMS), result) == "failed"
    start(browser, config(f"{sid}:draft"))
    start(browser, short)
    assert work(client) and draft_check(browser, sid) == "passed"
    assert work(client) and draft_check(browser, sid) == "failed"
    start(browser, config(f"{sid}:draft"))
    assert work(client) and draft_check(browser, sid) == "passed"
    response = browser.post(STRATEGY_COMMANDS, json={"action": "activate", "id": sid})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"instrumentId": "NSE:BANKNIFTY"},  # not the draft's instrument
        {"feeBps": 2},  # cheaper than the paper engine
        {"slippageBps": 4},
    ],
)
def test_runs_that_do_not_count_leave_the_check(
    client: TestClient, overrides: dict[str, Any]
) -> None:
    browser = Browser(client)
    browser.login_ready()
    sid = create_strategy(browser)
    assert start(browser, config(f"{sid}:draft", **overrides)).status_code == 202
    assert work(client)
    assert draft_check(browser, sid) == "unavailable"


def test_run_of_an_edited_draft_or_a_version_leaves_the_check(client: TestClient) -> None:
    browser = Browser(client)
    browser.login_ready()
    sid = create_strategy(browser)
    start(browser, config(f"{sid}:draft"))
    save_draft(browser, sid, positionSizeBps=800)  # edited after the run was queued
    assert work(client)
    assert draft_check(browser, sid) == "unavailable"

    # Same parameters as the queued run again: a later completion counts.
    save_draft(browser, sid)
    start(browser, config(f"{sid}:draft"))
    assert work(client) and draft_check(browser, sid) == "passed"
    save_draft(browser, sid)  # save-draft always resets the check
    assert draft_check(browser, sid) == "unavailable"

    activate(browser, sid)
    save_draft(browser, sid, positionSizeBps=800)
    start(browser, config(f"{sid}:1"))
    assert work(client)
    assert draft_check(browser, sid) == "unavailable"


def test_completion_waits_for_a_concurrent_save_draft(client: TestClient) -> None:
    """The worker holds the strategy row lock while it grades the draft, so a
    save-draft that arrives meanwhile waits and then resets the check. Without
    the lock the worker's verdict would overwrite the reset."""
    browser = Browser(client)
    browser.login_ready()
    sid = create_strategy(browser)
    start(browser, config(f"{sid}:draft"))
    pool = ThreadPoolExecutor(max_workers=1)
    pending: list[Any] = []

    def save_draft_meanwhile() -> None:
        # The same writes save-draft makes, from another connection. It blocks
        # on the row lock until the worker commits.
        pending.append(
            pool.submit(
                db_rows,
                _db(),
                "UPDATE strategies SET draft_parameters ="
                " jsonb_set(draft_parameters, '{position_size_bps}', '800'),"
                " draft_backtest = 'unavailable' WHERE id = :id",
                id=sid,
            )
        )
        time.sleep(0.5)  # let the update reach the lock (or commit, if unlocked)

    service(client)._after_strategy_lock = save_draft_meanwhile
    try:
        assert work(client)
        pending[0].result(timeout=10)
    finally:
        service(client)._after_strategy_lock = None
        pool.shutdown()
    (row,) = db_rows(_db(), "SELECT draft_parameters FROM strategies WHERE id = :id", id=sid)
    assert row["draft_parameters"]["position_size_bps"] == 800
    assert draft_check(browser, sid) == "unavailable"


def test_parameters_are_copied_when_queued(client: TestClient) -> None:
    browser = Browser(client)
    browser.login_ready()
    sid = create_strategy(browser, positionSizeBps=900)
    body = config(f"{sid}:draft")
    run_id = start(browser, body).json()["id"]
    save_draft(browser, sid, positionSizeBps=5000)
    assert work(client)
    result = browser.get(f"{RUNS}/{run_id}").json()["result"]
    assert result == expected_result(body, 900)
    assert result != expected_result(body, 5000)


def test_runs_are_listed_newest_first_and_capped_at_20(client: TestClient) -> None:
    browser = Browser(client)
    ref = draft_ref(browser)
    ids = []
    for _ in range(22):
        ids.append(start(browser, config(ref)).json()["id"])
        assert work(client)
    runs = browser.get(BASE).json()["data"]["runs"]
    assert [r["id"] for r in runs] == list(reversed(ids))[:20]


# ----------------------------------------------------------------------- failures


def test_worker_error_fails_the_run(
    client: TestClient, contract: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = Browser(client)
    ref = draft_ref(browser)
    run_id = start(browser, config(ref)).json()["id"]

    async def broken(*_: Any) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(service(client), "_replay", broken)
    assert work(client)
    run = browser.get(f"{RUNS}/{run_id}").json()
    check(contract, "BacktestRun", run)
    assert run["status"] == "failed"
    assert run["message"] == RUN_FAILED
    assert "result" not in run
    assert "boom" not in str(run)


def test_abandoned_runs_are_failed(client: TestClient, clock: FakeClock, contract: Any) -> None:
    browser = Browser(client)
    ref = draft_ref(browser)
    old = start(browser, config(ref)).json()["id"]
    recent = start(browser, config(ref)).json()["id"]
    db_rows(
        _db(),
        "UPDATE backtest_runs SET status = 'running', started_at = :at WHERE id = :id",
        at=clock.now,
        id=old,
    )
    clock.advance(200)
    db_rows(
        _db(),
        "UPDATE backtest_runs SET status = 'running', started_at = :at WHERE id = :id",
        at=clock.now,
        id=recent,
    )
    clock.advance(101)  # old: 301 s running, recent: 101 s
    assert client.portal is not None
    assert client.portal.call(service(client).fail_abandoned) == 1
    run = browser.get(f"{RUNS}/{old}").json()
    check(contract, "BacktestRun", run)
    assert (run["status"], run["message"]) == ("failed", RUN_ABANDONED)
    assert parse(run["asOf"]) == clock.now
    assert browser.get(f"{RUNS}/{recent}").json()["status"] == "running"


def test_worker_keeps_an_abandoned_outcome(client: TestClient, clock: FakeClock) -> None:
    """A slow worker must not overwrite a run that was failed as abandoned."""
    browser = Browser(client)
    ref = draft_ref(browser)
    run_id = start(browser, config(ref)).json()["id"]

    def abandon() -> None:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(
                db_rows,
                _db(),
                "UPDATE backtest_runs SET status = 'failed', message = 'gone' WHERE id = :id",
                id=run_id,
            ).result()

    service(client)._after_claim = abandon
    assert work(client)
    run = browser.get(f"{RUNS}/{run_id}").json()
    assert (run["status"], run["message"]) == ("failed", "gone")


def test_cancelled_worker_returns_its_run_to_the_queue(client: TestClient) -> None:
    """Shutdown cancelling the worker right after a claim must not strand the run."""
    browser = Browser(client)
    ref = draft_ref(browser)
    run_id = start(browser, config(ref)).json()["id"]

    def cancelled() -> None:
        raise asyncio.CancelledError

    service(client)._after_claim = cancelled
    with pytest.raises(BaseException):  # noqa: B017 - the portal re-raises the cancellation
        work(client)
    row = db_rows(_db(), "SELECT status, started_at FROM backtest_runs WHERE id = :id", id=run_id)
    assert row == [{"status": "queued", "started_at": None}]
    service(client)._after_claim = None
    assert work(client)
    assert browser.get(f"{RUNS}/{run_id}").json()["status"] == "completed"


# --------------------------------------------------------------------- validation


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"from": "2026-09-31"}, INVALID_DATES),
        ({"outOfSampleFrom": "2026-13-01"}, INVALID_DATES),
        ({"from": "2026-09-30"}, OUTSIDE_HISTORY),
        ({"to": "2026-11-24"}, OUTSIDE_HISTORY),
        ({"outOfSampleFrom": "2026-10-05"}, OUT_OF_ORDER),
        ({"outOfSampleFrom": "2026-11-23"}, OUT_OF_ORDER),
        ({"from": "2026-11-23", "outOfSampleFrom": "2026-11-20"}, OUT_OF_ORDER),
        ({"instrumentId": "NSE:UNKNOWN"}, UNKNOWN_INPUT),
        ({"strategyId": "nifty-momentum-2"}, UNKNOWN_INPUT),
        ({"strategyId": f"{uuid.uuid4()}:draft"}, UNKNOWN_INPUT),
        ({"strategyId": "{sid}:1"}, UNKNOWN_INPUT),
        ({"strategyId": "{sid}:01"}, UNKNOWN_INPUT),
        ({"strategyId": "{sid}:"}, UNKNOWN_INPUT),
        ({"strategyId": "{sid}:2147483648"}, UNKNOWN_INPUT),
        ({"strategyId": "{sid}:" + "9" * 27}, UNKNOWN_INPUT),
        ({"from": "2026-10-05", "outOfSampleFrom": "2026-10-07"}, TOO_FEW),
        ({"outOfSampleFrom": "2026-11-22"}, TOO_FEW),  # Nov 22 is a Sunday
        ({"capitalPaise": 99_999}, None),
        ({"capitalPaise": 1_000_000_001}, None),
        ({"capitalPaise": "100000"}, None),
        ({"feeBps": 501}, None),
        ({"slippageBps": -1}, None),
        ({"feeBps": 1.0}, None),
        ({"feeBps": True}, None),
        ({"from": "2026-10-5"}, None),
        ({"to": "2026-11-23T00:00:00Z"}, None),
        ({"extra": 1}, None),
        ({"strategyId": ""}, None),
        ({"strategyId": "x" * 65}, None),
    ],
)
def test_invalid_configs_are_400(
    browser: Browser, contract: Any, overrides: dict[str, Any], message: str | None
) -> None:
    ref = draft_ref(browser)
    sid = ref.split(":")[0]
    if isinstance(overrides.get("strategyId"), str):
        overrides = {**overrides, "strategyId": overrides["strategyId"].replace("{sid}", sid)}
    response = start(browser, config(ref, **overrides))
    assert response.status_code == 400, response.text
    check(contract, "BacktestError", response.json())
    assert response.json()["code"] == "INVALID_REQUEST"
    if message:
        assert response.json()["message"] == message
    assert run_count() == 0


def test_missing_fields_are_400(browser: Browser) -> None:
    ref = draft_ref(browser)
    for key in config(ref):
        body = {k: v for k, v in config(ref).items() if k != key}
        assert start(browser, body).status_code == 400, key
    assert run_count() == 0


def test_shortest_valid_window_is_accepted(client: TestClient) -> None:
    """Three warm-up and two out-of-sample sessions, the frontend's minimum."""
    browser = Browser(client)
    ref = draft_ref(browser)
    body = config(
        ref, **{"from": "2026-10-01", "outOfSampleFrom": "2026-10-06", "to": "2026-10-07"}
    )
    assert start(browser, body).status_code == 202
    assert work(client)
    assert len(browser.get(BASE).json()["data"]["runs"][0]["result"]["points"]) == 2


# ------------------------------------------------------------------- limits, users


def test_at_most_three_active_runs(client: TestClient, contract: Any) -> None:
    browser = Browser(client)
    ref = draft_ref(browser)
    for _ in range(3):
        assert start(browser, config(ref)).status_code == 202
    response = start(browser, config(ref))
    assert response.status_code == 409
    check(contract, "BacktestError", response.json())
    assert response.json()["code"] == "BACKTEST_CONFLICT"
    assert work(client)
    assert start(browser, config(ref)).status_code == 202
    assert run_count() == 4


def test_run_limit_holds_under_concurrency(client: TestClient) -> None:
    browser = Browser(client)
    ref = draft_ref(browser)
    active = browser.activate()
    headers = {
        **browser.headers(),
        "Cookie": "; ".join(f"{c.name}={c.value}" for c in browser.jar.jar),
    }
    active.cookies.clear()

    def attempt(_: int) -> int:
        return int(active.post(RUNS, json=config(ref), headers=headers).status_code)

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, range(8)))
    assert sorted(statuses) == [202] * 3 + [409] * 5
    assert run_count() == 3


def test_users_cannot_see_or_use_each_others_runs(make_app: Callable[..., TestClient]) -> None:
    client = make_app(backtest_worker_enabled=False)
    first, second = Browser(client), Browser(client)
    ref = draft_ref(first)
    second.login_ready(phone=OTHER_PHONE)
    run_id = start(first, config(ref)).json()["id"]
    response = second.get(f"{RUNS}/{run_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "BACKTEST_NOT_FOUND"
    data = second.get(BASE).json()["data"]
    assert data["runs"] == [] and data["strategies"] == []
    response = start(second, config(ref))
    assert (response.status_code, response.json()["message"]) == (400, UNKNOWN_INPUT)
    # The first user's three-run limit is not shared with the second user.
    second_ref = draft_ref(second)
    for _ in range(3):
        assert start(second, config(second_ref)).status_code == 202


@pytest.mark.parametrize("bad_id", ["nope", str(uuid.uuid4()), "x" * 64])
def test_unknown_run_ids_are_404(browser: Browser, bad_id: str) -> None:
    browser.login_ready()
    response = browser.get(f"{RUNS}/{bad_id}")
    assert response.status_code == 404
    assert response.json()["code"] == "BACKTEST_NOT_FOUND"


def test_disabled_is_503(make_app: Callable[..., TestClient], contract: Any) -> None:
    browser = Browser(make_app(backtests_enabled=False))
    browser.login_ready()
    for response in (
        browser.get(BASE),
        browser.get(f"{RUNS}/{uuid.uuid4()}"),
        start(browser, config(f"{uuid.uuid4()}:draft")),
    ):
        assert response.status_code == 503
        check(contract, "BacktestError", response.json())
        assert response.json()["code"] == "BACKTEST_UNAVAILABLE"


# ------------------------------------------------------------------ worker task


def test_background_worker_completes_runs(make_app: Callable[..., TestClient]) -> None:
    client = make_app(backtest_worker_poll_seconds=0.2)
    browser = Browser(client)
    ref = draft_ref(browser)
    run_id = start(browser, config(ref)).json()["id"]
    deadline = time.monotonic() + 10
    status = "queued"
    while status in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.05)
        status = browser.get(f"{RUNS}/{run_id}").json()["status"]
    assert status == "completed"


# ---------------------------------------------------------------- contract, DB


def test_every_contract_backtest_operation_is_implemented(contract: Any, browser: Browser) -> None:
    served = browser.get("/openapi.json").json()["paths"]
    paths = [p for p in contract["paths"] if p.startswith("/api/v1/backtests/")]
    assert len(paths) == 3
    for path in paths:
        assert path in served, f"{path} missing from the API"
        for method in contract["paths"][path]:
            assert method in served[path], f"{method.upper()} {path} missing"


def test_database_checks_and_cascade(client: TestClient) -> None:
    browser = Browser(client)
    ref = draft_ref(browser)
    start(browser, config(ref))
    with pytest.raises(Exception, match="result_iff_completed"):
        db_rows(_db(), "UPDATE backtest_runs SET status = 'completed', started_at = now()")
    with pytest.raises(Exception, match="message_iff_failed"):
        db_rows(_db(), "UPDATE backtest_runs SET message = 'x'")
    with pytest.raises(Exception, match="started_unless_queued"):
        db_rows(_db(), "UPDATE backtest_runs SET started_at = now()")
    db_rows(_db(), "DELETE FROM users")
    assert run_count() == 0


def test_check_constraints_keep_their_intended_names() -> None:
    rows = db_rows(
        _db(),
        "SELECT conname FROM pg_constraint WHERE contype = 'c'"
        " AND conrelid::regclass::text = 'backtest_runs'",
    )
    assert {r["conname"] for r in rows} == {
        "ck_backtest_runs_status_valid",
        "ck_backtest_runs_result_iff_completed",
        "ck_backtest_runs_message_iff_failed",
        "ck_backtest_runs_started_unless_queued",
    }


def test_backtest_migration_rolls_back_and_forward(db_url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = db_url

    def present() -> set[str]:
        rows = db_rows(db_url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {r["tablename"] for r in rows}

    assert "backtest_runs" in present()
    command.downgrade(cfg, "0004")
    assert "backtest_runs" not in present()
    assert {"strategies", "strategy_versions", "users"} <= present()
    command.upgrade(cfg, "head")
    assert "backtest_runs" in present()
