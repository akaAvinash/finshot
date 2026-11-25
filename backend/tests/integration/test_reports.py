"""Paper reports (contract 0.8.0): getPaperReport and exportPaperTrades.

Reports are checked against the pure replay engine, so every figure is tied to
the fills the paper ledger must hold."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient

from app.paper import engine
from app.reports import service as reports_module
from app.reports.service import ist_date
from tests.integration.test_paper import (
    PARAMS,
    STRATEGY_COMMANDS,
    TICK,
    _alembic,
    _db,
    active_strategy,
    check,
    expected_replay,
    ok,
    run_to_end,
    sessions,
    tick,
)
from tests.integration.test_paper import (
    contract as contract,  # fixture
)
from tests.support import OTHER_PHONE, PHONE, Browser, FakeClock, activate_authenticator, db_rows

pytestmark = pytest.mark.integration

REPORT = "/api/v1/reports/paper"
CSV = f"{REPORT}/trades.csv"


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    return make_app(
        paper_worker_enabled=False, backtest_worker_enabled=False, paper_tick_seconds=TICK
    )


def report(browser: Browser, **params: str) -> dict[str, Any]:
    response = browser.get(REPORT, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def replayed(client: TestClient, clock: FakeClock, **overrides: Any) -> tuple[Browser, str]:
    """A user whose SBIN strategy replayed every demo session."""
    browser = Browser(client)
    browser.login_ready()
    sid = active_strategy(browser, **overrides)
    ok(browser, {"action": "assign", "strategyId": sid})
    ok(browser, {"action": "start"})
    run_to_end(client, clock)
    return browser, sid


def expected_fills() -> list[engine.Fill]:
    _, fills = expected_replay("NSE:SBIN", PARAMS["positionSizeBps"], PARAMS["stopLossBps"])
    assert fills, "the demo replay should trade"
    return fills


# ------------------------------------------------------------- access and errors


def test_requires_a_session(browser: Browser, contract: Any) -> None:
    for path in (REPORT, CSV):
        response = browser.get(path)
        assert response.status_code == 401
        check(contract, "ReportError", response.json())
        assert response.json()["code"] == "UNAUTHENTICATED"
    # The session check runs before query validation.
    assert browser.get(REPORT, params={"from": "not-a-date"}).status_code == 401


@pytest.mark.parametrize(
    "params",
    [{"from": "2026-13-01"}, {"to": "yesterday"}, {"from": "2026-01-02", "to": "2026-01-01"}],
)
def test_invalid_period_is_400(browser: Browser, contract: Any, params: dict[str, str]) -> None:
    browser.login_ready()
    for path in (REPORT, CSV):
        response = browser.get(path, params=params)
        assert response.status_code == 400, response.text
        check(contract, "ReportError", response.json())
        assert response.json()["code"] == "INVALID_REQUEST"


def test_disabled_is_503(make_app: Callable[..., TestClient], contract: Any) -> None:
    browser = Browser(make_app(reports_enabled=False))
    browser.login_ready()
    for path in (REPORT, CSV):
        response = browser.get(path)
        assert response.status_code == 503
        check(contract, "ReportError", response.json())
        assert response.json()["code"] == "REPORTS_UNAVAILABLE"


def test_empty_until_a_strategy_is_assigned(browser: Browser, contract: Any) -> None:
    browser.login_ready()
    body = report(browser)
    assert body == {"status": "empty"}
    check(contract, "ReportResult", body)
    response = browser.get(CSV)
    assert response.status_code == 200
    assert response.text == ",".join(reports_module.CSV_HEADER) + "\r\n"


# ---------------------------------------------------------------- the report


def test_report_matches_the_replay(client: TestClient, clock: FakeClock, contract: Any) -> None:
    browser, sid = replayed(client, clock)
    fills = expected_fills()
    body = report(browser)
    check(contract, "ReportResult", body)
    data = body["data"]
    assert (data["source"], data["environment"]) == ("demo", "PAPER")

    sells = [f for f in fills if f.side == "Sell"]
    realised = sum(f.pnl_paise for f in fills)
    assert data["summary"] == {
        "realisedPaise": realised,
        "unrealisedPaise": 0,
        "netPaise": realised,
        "feesPaise": sum(f.fees_paise for f in fills),
        "fills": len(fills),
        "closedTrades": len(sells),
        "winningTrades": sum(1 for f in sells if f.pnl_paise > 0),
        "losingTrades": sum(1 for f in sells if f.pnl_paise < 0),
    }
    assert data["openPosition"] is None  # the replay ends flat

    by_day: dict[date, list[engine.Fill]] = defaultdict(list)
    for f in fills:
        by_day[ist_date(f.at)].append(f)
    assert data["daily"] == [
        {
            "date": day.isoformat(),
            "realisedPaise": sum(f.pnl_paise for f in day_fills),
            "feesPaise": sum(f.fees_paise for f in day_fills),
            "fills": len(day_fills),
        }
        for day, day_fills in sorted(by_day.items())
    ]
    days = sorted(by_day)
    assert data["period"] == {"from": days[0].isoformat(), "to": days[-1].isoformat()}

    ref = {"id": sid, "name": PARAMS["name"], "version": 1}
    assert data["strategies"] == [
        {
            "strategy": ref,
            "realisedPaise": realised,
            "feesPaise": sum(f.fees_paise for f in fills),
            "fills": len(fills),
            "closedTrades": len(sells),
        }
    ]
    journal = data["journal"]
    assert not data["journalTruncated"]
    assert [
        (t["side"], t["quantity"], t["fillPaise"], t["feesPaise"], t["pnlPaise"], t["reason"])
        for t in reversed(journal)
    ] == [(f.side, f.quantity, f.fill_paise, f.fees_paise, f.pnl_paise, f.reason) for f in fills]
    assert all(t["strategy"] == ref and t["replay"] == 1 for t in journal)
    assert all(t["instrument"] == "SBIN" for t in journal)

    final, _ = expected_replay("NSE:SBIN", PARAMS["positionSizeBps"], PARAMS["stopLossBps"])
    assert data["reconciliation"] == {
        "status": "matched",
        "replay": 1,
        "ledgerCashPaise": final.cash_paise,
        "accountCashPaise": final.cash_paise,
        "ledgerQuantity": 0,
        "accountQuantity": 0,
    }


def test_open_position_is_marked_at_the_last_close(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = Browser(client)
    browser.login_ready()
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    ok(browser, {"action": "start"})
    bars = sessions("NSE:SBIN")
    for _ in range(len(bars)):
        (account,) = db_rows(_db(), "SELECT * FROM paper_accounts")
        if account["position_quantity"] > 0:
            break
        assert tick(client)
        clock.advance(TICK)
    assert account["position_quantity"] > 0, "expected the replay to open a position"

    data = report(browser)["data"]
    check(contract, "PaperReport", data)
    last = bars[account["sessions_done"] - 1]
    mark = engine.paise(last.close)
    quantity, entry = account["position_quantity"], account["position_entry_paise"]
    unrealised = (mark - entry) * quantity - account["position_fees_paise"]
    position = data["openPosition"]
    assert position["instrument"] == "SBIN"
    assert (position["quantity"], position["entryPaise"]) == (quantity, entry)
    assert (position["markPaise"], position["unrealisedPaise"]) == (mark, unrealised)
    assert position["markedAt"].replace("Z", "+00:00") == last.time.isoformat()
    summary = data["summary"]
    assert summary["unrealisedPaise"] == unrealised
    assert summary["netPaise"] == summary["realisedPaise"] + unrealised
    reconciliation = data["reconciliation"]
    assert reconciliation["status"] == "matched"
    assert reconciliation["ledgerQuantity"] == quantity


def test_period_filters_fills_by_ist_session_date(client: TestClient, clock: FakeClock) -> None:
    browser, _ = replayed(client, clock)
    fills = expected_fills()
    days = sorted({ist_date(f.at) for f in fills})
    middle = days[len(days) // 2]

    data = report(browser, **{"from": middle.isoformat(), "to": middle.isoformat()})["data"]
    on_day = [f for f in fills if ist_date(f.at) == middle]
    assert data["period"] == {"from": middle.isoformat(), "to": middle.isoformat()}
    assert data["summary"]["fills"] == len(on_day)
    assert [d["date"] for d in data["daily"]] == [middle.isoformat()]
    assert len(data["journal"]) == len(on_day)

    after = report(browser, **{"from": middle.isoformat()})["data"]
    assert after["period"] == {"from": middle.isoformat(), "to": days[-1].isoformat()}
    assert after["summary"]["fills"] == sum(1 for f in fills if ist_date(f.at) >= middle)

    before = report(browser, to=middle.isoformat())["data"]
    assert before["period"] == {"from": days[0].isoformat(), "to": middle.isoformat()}

    # A period with no fills: open sides stay null; the reconciliation and
    # open position still describe the current replay.
    none = report(browser, to="2000-01-01")["data"]
    assert none["period"] == {"from": None, "to": "2000-01-01"}
    assert none["summary"]["fills"] == 0
    assert none["daily"] == none["strategies"] == none["journal"] == []
    assert none["reconciliation"]["status"] == "matched"


def test_fills_are_attributed_per_replay(client: TestClient, clock: FakeClock) -> None:
    browser, first = replayed(client, clock)
    second = active_strategy(browser, name="SBIN Momentum B", positionSizeBps=500)
    ok(browser, {"action": "assign", "strategyId": second})
    ok(browser, {"action": "start"})
    run_to_end(client, clock)

    data = report(browser)["data"]
    refs = [s["strategy"] for s in data["strategies"]]
    assert refs == [
        {"id": first, "name": PARAMS["name"], "version": 1},
        {"id": second, "name": "SBIN Momentum B", "version": 1},
    ]
    assert {t["replay"] for t in data["journal"]} == {1, 2}
    assert data["journal"][0]["replay"] == 2  # newest first
    assert data["reconciliation"]["replay"] == 2

    # Fills of a replay recorded before 0007 have no attribution.
    db_rows(_db(), "DELETE FROM paper_replays WHERE replay = 1")
    data = report(browser)["data"]
    assert data["strategies"][-1]["strategy"] is None
    assert data["strategies"][0]["strategy"]["id"] == second
    assert all(t["strategy"] is None for t in data["journal"] if t["replay"] == 1)


def test_versions_of_one_strategy_keep_their_pinned_names(
    client: TestClient, clock: FakeClock
) -> None:
    browser, sid = replayed(client, clock)
    # Version 2 of the same strategy, renamed, then a second replay of it.
    assert browser.post(STRATEGY_COMMANDS, json={"action": "pause", "id": sid}).status_code == 200
    renamed = {**PARAMS, "name": "SBIN Momentum Renamed"}
    response = browser.post(
        STRATEGY_COMMANDS, json={"action": "save-draft", "id": sid, "parameters": renamed}
    )
    assert response.status_code == 200, response.text
    db_rows(_db(), "UPDATE strategies SET draft_backtest = 'passed' WHERE id = :id", id=sid)
    response = browser.post(STRATEGY_COMMANDS, json={"action": "activate", "id": sid})
    assert response.status_code == 200, response.text
    ok(browser, {"action": "assign", "strategyId": sid})
    ok(browser, {"action": "start"})
    run_to_end(client, clock)

    v1 = {"id": sid, "name": PARAMS["name"], "version": 1}
    v2 = {"id": sid, "name": "SBIN Momentum Renamed", "version": 2}
    data = report(browser)["data"]
    assert [s["strategy"] for s in data["strategies"]] == [v1, v2]
    by_replay = {t["replay"]: t["strategy"] for t in data["journal"]}
    assert by_replay == {1: v1, 2: v2}

    rows = list(csv.reader(io.StringIO(browser.get(CSV).text)))[1:]
    assert {(r[2], r[3], r[4]) for r in rows} == {
        ("1", PARAMS["name"], "1"),
        ("2", "SBIN Momentum Renamed", "2"),
    }


def test_extreme_period_bounds(client: TestClient, clock: FakeClock) -> None:
    browser, _ = replayed(client, clock)
    fills = len(expected_fills())
    bounds = {"from": date.min.isoformat(), "to": date.max.isoformat()}
    data = report(browser, **bounds)["data"]
    assert data["period"] == {"from": "0001-01-01", "to": "9999-12-31"}
    assert data["summary"]["fills"] == fills
    response = browser.get(CSV, params=bounds)
    assert response.status_code == 200
    assert len(list(csv.reader(io.StringIO(response.text)))) == 1 + fills
    assert report(browser, to=date.min.isoformat())["data"]["summary"]["fills"] == 0
    assert report(browser, **{"from": date.max.isoformat()})["data"]["summary"]["fills"] == 0


def test_journal_is_capped(
    client: TestClient, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser, _ = replayed(client, clock)
    fills = expected_fills()
    monkeypatch.setattr(reports_module, "JOURNAL_LIMIT", 2)
    data = report(browser)["data"]
    assert len(data["journal"]) == 2
    assert data["journalTruncated"] is True
    assert data["summary"]["fills"] == len(fills)  # totals still cover every fill


def test_reconciliation_reports_a_mismatch(client: TestClient, clock: FakeClock) -> None:
    browser, _ = replayed(client, clock)
    db_rows(_db(), "UPDATE paper_accounts SET cash_paise = cash_paise + 1")
    reconciliation = report(browser)["data"]["reconciliation"]
    assert reconciliation["status"] == "mismatch"
    assert reconciliation["accountCashPaise"] == reconciliation["ledgerCashPaise"] + 1


def test_users_are_isolated(client: TestClient, clock: FakeClock) -> None:
    replayed(client, clock)
    other = Browser(client)
    other.login_ready(phone=OTHER_PHONE)
    assert report(other) == {"status": "empty"}
    assert other.get(CSV).text.count("\r\n") == 1  # header only


# ------------------------------------------------------------------------ CSV


def test_csv_lists_every_fill(client: TestClient, clock: FakeClock) -> None:
    browser, _ = replayed(client, clock)
    fills = expected_fills()
    response = browser.get(CSV)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert (
        response.headers["content-disposition"] == 'attachment; filename="tradeo-paper-trades.csv"'
    )
    text = response.text
    assert not text.startswith("﻿")
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    rows = list(csv.reader(io.StringIO(text)))
    assert tuple(rows[0]) == reports_module.CSV_HEADER
    body = rows[1:]
    assert len(body) == len(fills)
    for row, f in zip(body, fills, strict=True):  # oldest first
        record = dict(zip(reports_module.CSV_HEADER, row, strict=True))
        assert record["date"] == ist_date(f.at).isoformat()
        assert record["filled_at"].endswith("Z")
        assert (record["replay"], record["strategy"], record["version"]) == (
            "1",
            PARAMS["name"],
            "1",
        )
        assert (record["instrument"], record["side"], record["reason"]) == (
            "SBIN",
            f.side,
            f.reason,
        )
        assert record["quantity"] == str(f.quantity)
        assert record["fill_inr"] == reports_module.inr(f.fill_paise)
        assert record["fees_inr"] == reports_module.inr(f.fees_paise)
        assert record["pnl_inr"] == reports_module.inr(f.pnl_paise)

    middle = sorted({ist_date(f.at) for f in fills})[1]
    filtered = browser.get(CSV, params={"from": middle.isoformat(), "to": middle.isoformat()})
    expected = sum(1 for f in fills if ist_date(f.at) == middle)
    assert len(list(csv.reader(io.StringIO(filtered.text)))) == 1 + expected


def test_csv_escapes_spreadsheet_formulas(client: TestClient, clock: FakeClock) -> None:
    browser, _ = replayed(client, clock, name="=HYPERLINK(1), test")
    rows = list(csv.reader(io.StringIO(browser.get(CSV).text)))
    assert {r[3] for r in rows[1:]} == {"'=HYPERLINK(1), test"}
    assert '"\'=HYPERLINK(1), test"' in browser.get(CSV).text  # quoted: it holds a comma


# ------------------------------------------------------------------ migration


def test_migration_backfills_the_current_replay(
    client: TestClient, clock: FakeClock, db_url: str
) -> None:
    browser, sid = replayed(client, clock)
    command.downgrade(_alembic(db_url), "0006")
    assert db_rows(db_url, "SELECT to_regclass('paper_replays') AS t")[0]["t"] is None
    command.upgrade(_alembic(db_url), "head")
    activate_authenticator(PHONE)  # the downgrade dropped the authenticator table
    rows = db_rows(db_url, "SELECT * FROM paper_replays")
    assert [
        (str(r["strategy_id"]), r["replay"], r["version_number"], r["strategy_name"]) for r in rows
    ] == [(sid, 1, 1, PARAMS["name"])]
    assert report(browser)["data"]["strategies"][0]["strategy"]["id"] == sid
    with pytest.raises(Exception, match="append-only"):
        db_rows(db_url, "UPDATE paper_replays SET version_number = 2")
