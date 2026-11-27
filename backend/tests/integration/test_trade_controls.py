"""Paper Trade Controls: /api/v1/settings/trade-controls over real Postgres and Redis."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from alembic import command
from fastapi.testclient import TestClient

from app.paper import controls as tc
from app.paper import engine
from tests.integration.test_paper import (
    CONTRACT_PATH,
    _alembic,
    active_strategy,
    check,
    ok,
    run_to_end,
    sessions,
)
from tests.support import OTHER_PHONE, Browser, FakeClock, db_rows

pytestmark = pytest.mark.integration

URL = "/api/v1/settings/trade-controls"
HISTORY = f"{URL}/history"

VALID: dict[str, Any] = {
    "lossLimitPaise": 1_000_000,
    "tradeLimit": 4,
    "profitLimitPaise": 500_000,
    "maxConsecutiveLosses": 2,
    "stopLossBps": 100,
    "takeProfitBps": 300,
    "maxRiskPerTradePaise": 500_000,
    "maxPositionSizeBps": 500,
}


@pytest.fixture
def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    return make_app(paper_worker_enabled=False, backtest_worker_enabled=False)


def open_step_up(browser: Browser, clock: FakeClock) -> None:
    db_rows(
        os.environ["TEST_DATABASE_URL"],
        "UPDATE sessions SET step_up_until = :t",
        t=clock.now + timedelta(hours=1),
    )


def save(browser: Browser, controls: dict[str, Any], revision: int, **kw: Any) -> Any:
    return browser.send(
        "PUT",
        URL,
        json={"expectedRevision": revision, "controls": controls},
        headers=browser.headers(),
        **kw,
    )


@pytest.fixture
def user(client: TestClient, clock: FakeClock) -> Browser:
    browser = Browser(client)
    browser.login_ready()
    open_step_up(browser, clock)
    return browser


def test_requires_a_session(browser: Browser) -> None:
    assert browser.get(URL).status_code == 401
    assert browser.get(HISTORY).status_code == 401
    browser.get_csrf()
    assert save(browser, VALID, 0).status_code == 401


def test_defaults_before_the_first_save(user: Browser, contract: Any) -> None:
    response = user.get(URL)
    assert response.status_code == 200, response.text
    body = response.json()
    check(contract, "TradeControlsSettings", body)
    assert body["revision"] == 0 and body["updatedAt"] is None
    assert body["controls"] == body["defaults"]
    assert body["controls"]["lossLimitPaise"] == engine.LOSS_LIMIT_PAISE
    assert body["controls"]["profitLimitPaise"] is None
    assert body["bounds"]["lossLimitPaise"] == {
        "minimum": 1,
        "maximum": engine.LOSS_LIMIT_PAISE,
        "nullable": False,
    }
    history = user.get(HISTORY)
    assert history.status_code == 200 and history.json() == {"changes": []}
    check(contract, "TradeControlsHistory", history.json())


def test_save_applies_audits_and_records_history(
    user: Browser,
    contract: Any,
    db_url: str,
) -> None:
    response = save(user, VALID, 0)
    assert response.status_code == 200, response.text
    body = response.json()
    check(contract, "TradeControlsSettings", body)
    assert body["revision"] == 1 and body["controls"] == VALID
    assert user.get(URL).json()["controls"] == VALID

    history = user.get(HISTORY).json()
    check(contract, "TradeControlsHistory", history)
    (change,) = history["changes"]
    assert change["revision"] == 1
    assert {f["field"] for f in change["fields"]} == {
        "lossLimitPaise",
        "tradeLimit",
        "profitLimitPaise",
        "maxConsecutiveLosses",
        "stopLossBps",
        "takeProfitBps",
        "maxRiskPerTradePaise",
        "maxPositionSizeBps",
    }
    loss = next(f for f in change["fields"] if f["field"] == "lossLimitPaise")
    assert loss == {"field": "lossLimitPaise", "from": engine.LOSS_LIMIT_PAISE, "to": 1_000_000}

    rows = db_rows(
        db_url,
        "SELECT metadata_redacted AS m FROM audit_events"
        " WHERE action = 'settings.trade_controls_updated'",
    )
    assert len(rows) == 1
    assert rows[0]["m"]["revision"] == 1 and "lossLimitPaise" in rows[0]["m"]["fields"]
    assert "1000000" not in str(rows[0]["m"])  # names only, never values


def test_saving_the_same_values_changes_nothing(user: Browser, db_url: str) -> None:
    assert save(user, VALID, 0).status_code == 200
    again = save(user, VALID, 1)
    assert again.status_code == 200 and again.json()["revision"] == 1
    assert len(user.get(HISTORY).json()["changes"]) == 1
    rows = db_rows(
        db_url, "SELECT 1 FROM audit_events WHERE action = 'settings.trade_controls_updated'"
    )
    assert len(rows) == 1


def test_history_is_newest_first_and_lists_only_changed_fields(user: Browser) -> None:
    assert save(user, VALID, 0).status_code == 200
    assert save(user, {**VALID, "tradeLimit": 3}, 1).status_code == 200
    changes = user.get(HISTORY).json()["changes"]
    assert [c["revision"] for c in changes] == [2, 1]
    assert changes[0]["fields"] == [{"field": "tradeLimit", "from": 4, "to": 3}]


def test_stale_revision_conflicts(user: Browser) -> None:
    assert save(user, VALID, 0).status_code == 200
    stale = save(user, {**VALID, "tradeLimit": 2}, 0)
    assert stale.status_code == 409
    assert stale.json()["code"] == "TRADE_CONTROLS_REVISION_CONFLICT"
    assert user.get(URL).json()["controls"]["tradeLimit"] == 4
    ahead = save(user, VALID, 5)
    assert ahead.status_code == 409


def test_values_outside_the_bounds_are_400_with_field_errors(
    user: Browser,
    contract: Any,
) -> None:
    bad = {**VALID, "lossLimitPaise": engine.LOSS_LIMIT_PAISE + 1, "tradeLimit": 11}
    response = save(user, bad, 0)
    assert response.status_code == 400
    body = response.json()
    check(contract, "TradeControlsError", body)
    assert body["code"] == "TRADE_CONTROLS_OUT_OF_BOUNDS"
    assert [e["field"] for e in body["fieldErrors"]] == ["lossLimitPaise", "tradeLimit"]
    assert body["fieldErrors"][0]["bound"] == {
        "minimum": 1,
        "maximum": engine.LOSS_LIMIT_PAISE,
        "nullable": False,
    }
    assert user.get(URL).json()["revision"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {"controls": VALID},
        {"expectedRevision": 0},
        {"expectedRevision": -1, "controls": VALID},
        {"expectedRevision": "0", "controls": VALID},
        {"expectedRevision": 0, "controls": {**VALID, "tradeLimit": 1.5}},
        {"expectedRevision": 0, "controls": {**VALID, "tradeLimit": 0}},
        {"expectedRevision": 0, "controls": {**VALID, "tradeLimit": None}},
        {"expectedRevision": 0, "controls": {**VALID, "stopLossBps": 10_000}},
        {"expectedRevision": 0, "controls": {**VALID, "extra": 1}},
        {"expectedRevision": 0, "controls": {k: v for k, v in VALID.items() if k != "tradeLimit"}},
        {"expectedRevision": 0, "controls": VALID, "extra": 1},
    ],
)
def test_malformed_bodies_are_400_invalid_request(user: Browser, body: dict[str, Any]) -> None:
    response = user.send("PUT", URL, json=body, headers=user.headers())
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INVALID_REQUEST"
    assert user.get(URL).json()["revision"] == 0


def test_optional_controls_can_be_turned_off_again(user: Browser) -> None:
    assert save(user, VALID, 0).status_code == 200
    off = {**VALID, "profitLimitPaise": None, "stopLossBps": None, "takeProfitBps": None}
    response = save(user, off, 1)
    assert response.status_code == 200 and response.json()["controls"] == off


def test_save_check_order_is_csrf_then_step_up_then_validation(
    client: TestClient, clock: FakeClock
) -> None:
    browser = Browser(client)
    browser.login_ready()
    # No step-up window yet: CSRF first, then step-up, before the body is read.
    bad_csrf = browser.send("PUT", URL, json={"junk": 1}, headers=browser.headers(csrf="wrong"))
    assert (bad_csrf.status_code, bad_csrf.json()["code"]) == (403, "CSRF_FAILED")
    needs = browser.send("PUT", URL, json={"junk": 1}, headers=browser.headers())
    assert (needs.status_code, needs.json()["code"]) == (403, "STEP_UP_REQUIRED")
    assert browser.get(URL).json()["revision"] == 0
    open_step_up(browser, clock)
    assert save(browser, VALID, 0).status_code == 200


def test_saving_is_blocked_while_the_engine_runs(client: TestClient, user: Browser) -> None:
    sid = active_strategy(user)
    ok(user, {"action": "assign", "strategyId": sid})
    ok(user, {"action": "start"})
    blocked = save(user, VALID, 0)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "TRADE_CONTROLS_ENGINE_RUNNING"
    assert user.get(URL).json()["revision"] == 0
    ok(user, {"action": "pause"})
    assert save(user, VALID, 0).status_code == 200


def test_controls_are_per_user(client: TestClient, clock: FakeClock, user: Browser) -> None:
    assert save(user, VALID, 0).status_code == 200
    other = Browser(client)
    other.login_ready(phone=OTHER_PHONE)
    body = other.get(URL).json()
    assert body["revision"] == 0 and body["controls"] == body["defaults"]
    assert other.get(HISTORY).json() == {"changes": []}


def test_bounds_match_the_engine_ceilings() -> None:
    assert tc.BOUNDS["lossLimitPaise"].maximum == engine.LOSS_LIMIT_PAISE
    assert tc.BOUNDS["tradeLimit"].maximum == engine.TRADE_LIMIT
    assert tc.BOUNDS["maxRiskPerTradePaise"].maximum == engine.PER_TRADE_RISK_PAISE
    assert tc.out_of_bounds(tc.DEFAULTS) == []


def test_saved_controls_drive_the_replay_like_the_engine(
    client: TestClient, user: Browser, clock: FakeClock
) -> None:
    sid = active_strategy(user)  # version 1: size 900 bps, stop 125 bps
    ok(user, {"action": "assign", "strategyId": sid})
    controls = {**VALID, "takeProfitBps": 150, "tradeLimit": 6, "maxConsecutiveLosses": 1}
    assert save(user, controls, 0).status_code == 200
    ok(user, {"action": "start"})
    run_to_end(client, clock)

    limits, size, stop = tc.limits_for(controls, 900, 125)
    bars = sessions("NSE:SBIN")
    state = engine.State(cash_paise=engine.CAPITAL_PAISE)
    queued: engine.QueuedOrder | None = None
    expected: list[engine.Fill] = []
    while state.sessions_done < len(bars):
        out = engine.step(
            state, bars, queued, size_bps=size, stop_loss_bps=stop, symbol="X", limits=limits
        )
        expected.extend(out.fills)
        queued = None
        if out.new_order is not None:
            queued = engine.QueuedOrder(out.new_order.side, out.new_order.quantity)

    data = user.get("/api/v1/auto-trading/paper").json()["data"]
    assert data["risk"]["controlsRevision"] == 1
    assert data["risk"]["tradeLimit"] == 6
    stored = db_rows(
        os.environ["TEST_DATABASE_URL"],
        "SELECT side, quantity, fill_paise, reason FROM paper_trades ORDER BY filled_at, id",
    )
    assert [(r["side"], r["quantity"], r["fill_paise"], r["reason"]) for r in stored] == [
        (f.side, f.quantity, f.fill_paise, f.reason) for f in expected
    ]
    assert len(expected) > 0


def test_migration_0013_keeps_take_profit_trades_on_rollback_and_backfills_the_peak(
    user: Browser, db_url: str
) -> None:
    sid = active_strategy(user)
    ok(user, {"action": "assign", "strategyId": sid})
    db_rows(
        db_url,
        "INSERT INTO paper_trades (user_id, replay, instrument, side, quantity, fill_paise,"
        " fees_paise, pnl_paise, reason, filled_at, created_at)"
        " SELECT user_id, replay, 'SBIN', 'Sell', 7, 10100, 4, 321, 'take-profit', now(), now()"
        " FROM paper_accounts",
    )
    db_rows(db_url, "UPDATE paper_accounts SET session_pnl_paise = 50000")
    ids_before = [r["id"] for r in db_rows(db_url, "SELECT id FROM paper_trades")]
    assert len(ids_before) == 1
    command.downgrade(_alembic(db_url), "0012")
    assert [r["id"] for r in db_rows(db_url, "SELECT id FROM paper_trades")] == ids_before
    rows = db_rows(db_url, "SELECT quantity, fees_paise, pnl_paise, reason FROM paper_trades")
    assert [(r["quantity"], r["fees_paise"], r["pnl_paise"], r["reason"]) for r in rows] == [
        (7, 4, 321, "signal-exit")
    ]
    command.upgrade(_alembic(db_url), "head")
    peak = db_rows(db_url, "SELECT session_peak_pnl_paise AS p FROM paper_accounts")
    assert peak[0]["p"] == 50000
