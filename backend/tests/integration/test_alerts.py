"""Alerts (contract 0.9.0): listAlerts, acknowledgeAlert, get/updateAlertPreferences,
the in-transaction producers and the alert worker, over real PostgreSQL and Redis.

The app runs without its background workers; tests drive paper ticks and the
alert worker under the fake clock, so every alert is deterministic."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Callable
from typing import Any

import pytest
import sqlalchemy.exc
from alembic import command
from fastapi.testclient import TestClient

from app.alerts.catalog import CATALOG
from app.alerts.service import AlertService
from tests.integration.test_paper import (
    TICK,
    _alembic,
    _db,
    active_strategy,
    check,
    ok,
    run_to_end,
)
from tests.integration.test_paper import (
    contract as contract,  # fixture
)
from tests.support import OTHER_PHONE, Browser, FakeClock, db_rows

pytestmark = pytest.mark.integration

ALERTS = "/api/v1/alerts"
PREFS = f"{ALERTS}/preferences"
BROKERS = "/api/v1/brokers/preview"


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    return make_app(
        paper_worker_enabled=False,
        backtest_worker_enabled=False,
        agent_worker_enabled=False,
        alert_worker_enabled=False,
        paper_tick_seconds=TICK,
        # Outlasts the 8-hour demo broker connection.
        session_idle_ttl_seconds=86_400,
    )


def worker(client: TestClient) -> int:
    assert client.portal is not None
    service: AlertService = client.app.state.alerts  # type: ignore[attr-defined]
    recorded: int = client.portal.call(service.run_once)
    return recorded


def signed_in(client: TestClient, phone: str | None = None) -> Browser:
    browser = Browser(client)
    if phone is None:
        browser.login()
    else:
        browser.login(phone=phone)
    return browser


def page(browser: Browser, contract: Any, **params: Any) -> dict[str, Any]:
    response = browser.get(ALERTS, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    check(contract, "AlertPage", body)
    return body


def every_alert(browser: Browser, contract: Any, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(1000):
        query = dict(params) if cursor is None else {**params, "cursor": cursor}
        body = page(browser, contract, **query)
        items.extend(body["items"])
        cursor = body["nextCursor"]
        if cursor is None:
            return items
    raise AssertionError("pagination did not end")


def kinds(items: list[dict[str, Any]]) -> list[str]:
    return [item["kind"] for item in items]


def ack(browser: Browser, alert_id: str, **kwargs: Any) -> Any:
    return browser.post(f"{ALERTS}/{alert_id}/ack", **kwargs)


def user_id(phone_browser: Browser) -> str:
    me = phone_browser.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text
    value: str = me.json()["user"]["id"]
    return value


def insert_alerts(uid: str, count: int, *, kind: str = "PAPER_REPLAY_FINISHED") -> None:
    info = CATALOG[kind]  # type: ignore[index]
    for n in range(count):
        db_rows(
            _db(),
            "INSERT INTO alerts (user_id, dedupe_key, kind, source, severity, environment,"
            " title, message, occurred_at, created_at) VALUES (:u, :k, :kind, :source,"
            " :severity, :env, :title, 'synthetic', now(), now())",
            u=uid,
            k=f"test:{kind}:{n}:{uuid.uuid4()}",
            kind=kind,
            source=info.source,
            severity=info.severity,
            env=info.environment,
            title=info.title,
        )


# ------------------------------------------------------------------ auth and CSRF


def test_requires_a_session(client: TestClient, contract: Any) -> None:
    browser = Browser(client)
    for path in (ALERTS, PREFS):
        response = browser.get(path)
        assert response.status_code == 401
        check(contract, "AlertError", response.json())
        assert response.json()["code"] == "UNAUTHENTICATED"
    browser.get_csrf()
    assert ack(browser, str(uuid.uuid4())).status_code == 401
    put = browser.send(
        "PUT", PREFS, json={"inApp": {"warning": True, "info": True}}, headers=browser.headers()
    )
    assert put.status_code == 401


def test_writes_require_a_session_csrf_token(client: TestClient, contract: Any) -> None:
    browser = signed_in(client)
    (alert,) = page(browser, contract)["items"]
    response = ack(browser, alert["id"], headers=browser.headers(csrf="forged"))
    assert response.status_code == 403
    check(contract, "AlertError", response.json())
    assert response.json()["code"] == "CSRF_FAILED"
    put = browser.send(
        "PUT",
        PREFS,
        json={"inApp": {"warning": False, "info": False}},
        headers=browser.headers(origin="https://evil.example"),
    )
    assert put.status_code == 403
    # Nothing was written.
    assert page(browser, contract)["items"][0]["acknowledgedAt"] is None
    assert browser.get(PREFS).json()["updatedAt"] is None


def test_disabled_is_503(make_app: Callable[..., TestClient], contract: Any) -> None:
    browser = signed_in(make_app(alerts_enabled=False, alert_worker_enabled=False))
    for path in (ALERTS, PREFS):
        response = browser.get(path)
        assert response.status_code == 503
        check(contract, "AlertError", response.json())
        assert response.json()["code"] == "ALERTS_UNAVAILABLE"
    # Producers keep recording, so nothing is lost while the inbox is off.
    assert db_rows(_db(), "SELECT kind FROM alerts") == [{"kind": "NEW_SIGN_IN"}]


# ----------------------------------------------------------------- producers


def test_sign_in_and_sign_out_everywhere_alert(client: TestClient, contract: Any) -> None:
    browser = signed_in(client)
    (alert,) = page(browser, contract)["items"]
    assert alert["kind"] == "NEW_SIGN_IN"
    assert (alert["source"], alert["severity"], alert["environment"]) == ("security", "info", None)
    sessions = browser.get("/api/v1/auth/sessions").json()["sessions"]
    assert alert["link"] == {"kind": "session", "id": sessions[0]["id"]}
    assert alert["occurredAt"] == alert["createdAt"]
    assert alert["acknowledgedAt"] is None

    other = signed_in(client)  # same phone, second device
    assert kinds(page(other, contract)["items"]) == ["NEW_SIGN_IN", "NEW_SIGN_IN"]
    response = other.post("/api/v1/auth/logout-all")
    assert response.status_code == 204
    third = signed_in(client)
    items = page(third, contract)["items"]
    assert kinds(items) == ["NEW_SIGN_IN", "SIGNED_OUT_EVERYWHERE", "NEW_SIGN_IN", "NEW_SIGN_IN"]
    assert "2 revoked" in items[1]["message"]
    # Links to the revoked sessions still verify: the rows exist and are the caller's.
    assert all(item["link"] for item in items if item["kind"] == "NEW_SIGN_IN")


def test_paper_halt_and_finished_replay_alert(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = signed_in(client)
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    ok(browser, {"action": "start"})
    run_to_end(client, clock)
    ok(browser, {"action": "halt", "confirmation": "STOP"})
    items = page(browser, contract, source="paper")["items"]
    assert kinds(items)[0] == "PAPER_ENGINE_HALTED"
    assert items[0]["severity"] == "critical"
    assert items[0]["environment"] == "PAPER"
    finished = [i for i in items if i["kind"] == "PAPER_REPLAY_FINISHED"]
    assert len(finished) == 1
    assert finished[0]["link"] == {"kind": "paper-replay", "id": "1"}
    # Every stop-loss fill has one alert linked to its trade.
    stops = db_rows(_db(), "SELECT id FROM paper_trades WHERE reason = 'stop-loss'")
    stop_alerts = [i for i in items if i["kind"] == "PAPER_STOP_LOSS_EXIT"]
    assert sorted(a["link"]["id"] for a in stop_alerts) == sorted(str(r["id"]) for r in stops)


def test_risk_limit_and_cancelled_order_alerts(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    """The demo data rarely trips these, so the engine outcomes are forced."""
    from app.paper import engine

    browser = signed_in(client)
    sid = active_strategy(browser)
    ok(browser, {"action": "assign", "strategyId": sid})
    ok(browser, {"action": "start"})
    real_step = engine.step

    def forced(*args: Any, **kwargs: Any) -> engine.StepResult:
        out = real_step(*args, **kwargs)
        out.risk_blocked = True
        return out

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(engine, "step", forced)
        from tests.integration.test_paper import tick

        assert tick(client)
        clock.advance(TICK)
        assert tick(client)
    items = page(browser, contract, source="paper")["items"]
    limits = [i for i in items if i["kind"] == "PAPER_RISK_LIMIT_REACHED"]
    assert len(limits) == 2  # once per replayed session
    assert {i["severity"] for i in limits} == {"critical"}

    # A queued buy the cash cannot cover (not even one unit) is cancelled at the open.
    uid = user_id(browser)
    db_rows(_db(), "UPDATE paper_orders SET status = 'cancelled' WHERE status = 'queued'")
    db_rows(
        _db(),
        "UPDATE paper_accounts SET cash_paise = 0, position_quantity = 0,"
        " position_entry_paise = NULL, position_stop_paise = NULL, position_fees_paise = 0",
    )
    db_rows(
        _db(),
        "INSERT INTO paper_orders (user_id, replay, instrument, side, quantity, limit_paise,"
        " status, created_at, updated_at) VALUES (:u, 1, 'SBIN', 'Buy', 1000000000, 100,"
        " 'queued', now(), now())",
        u=uid,
    )
    clock.advance(TICK)
    assert tick(client)
    cancelled = [
        i
        for i in page(browser, contract, source="paper")["items"]
        if i["kind"] == "PAPER_ORDER_CANCELLED"
    ]
    assert len(cancelled) == 1
    (order,) = db_rows(_db(), "SELECT id, status FROM paper_orders WHERE quantity = 1000000000")
    assert order["status"] == "cancelled"
    assert cancelled[0]["link"] == {"kind": "paper-order", "id": str(order["id"])}


def test_broker_expiry_alerts_once_and_disconnect_alerts(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = signed_in(client)
    response = browser.post(f"{BROKERS}/zerodha/actions", json={"action": "connect"})
    assert response.status_code == 200, response.text
    assert worker(client) == 0  # not expired yet
    clock.advance(8 * 3600)  # exactly at expiresAt: expired
    assert worker(client) == 1
    assert worker(client) == 0  # a retry records nothing new
    (expired,) = page(browser, contract, source="brokers")["items"]
    assert expired["kind"] == "BROKER_CONNECTION_EXPIRED"
    assert expired["severity"] == "critical"
    assert expired["environment"] == "DEMO"
    assert expired["link"] == {"kind": "broker", "id": "zerodha"}
    assert expired["occurredAt"] == expired["createdAt"]  # recorded exactly at the expiry

    # A reconnect sets a new expiry, which can alert again later.
    assert (
        browser.post(f"{BROKERS}/zerodha/actions", json={"action": "reconnect"}).status_code == 200
    )
    clock.advance(8 * 3600)
    assert worker(client) == 1
    browser.login()  # the first session reached its absolute expiry
    assert (
        browser.post(f"{BROKERS}/zerodha/actions", json={"action": "disconnect"}).status_code == 200
    )
    items = page(browser, contract, source="brokers")["items"]
    assert kinds(items) == [
        "BROKER_DISCONNECTED",
        "BROKER_CONNECTION_EXPIRED",
        "BROKER_CONNECTION_EXPIRED",
    ]
    # The connection is gone, so no link verifies any more.
    assert [i["link"] for i in items] == [None, None, None]
    assert worker(client) == 0


def test_reconciliation_mismatch_alerts_once_per_agent_event(
    client: TestClient, contract: Any
) -> None:
    browser = signed_in(client)
    uid = user_id(browser)
    for key, reason in (("m1", "RECONCILIATION_MISMATCH"), ("ok", "RECONCILIATION_MATCHED")):
        db_rows(
            _db(),
            "INSERT INTO agent_events (user_id, agent_id, dedupe_key, reason_code, severity,"
            " message, data_as_of, created_at) VALUES (:u, 'execution-monitor', :k, :r,"
            " 'warning', 'The ledger does not match.', now(), now())",
            u=uid,
            k=key,
            r=reason,
        )
    assert worker(client) == 1
    assert worker(client) == 0
    (alert,) = page(browser, contract, source="agents")["items"]
    assert alert["kind"] == "RECONCILIATION_MISMATCH"
    assert alert["message"] == "The ledger does not match."


# ------------------------------------------------------------ acknowledgement


def test_acknowledge_is_idempotent_and_owner_only(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    owner = signed_in(client)
    stranger = signed_in(client, phone=OTHER_PHONE)
    (alert,) = page(owner, contract)["items"]
    assert page(owner, contract)["unread"] == {"total": 1, "critical": 0, "warning": 0, "info": 1}

    # Another user's alert looks like one that does not exist.
    response = ack(stranger, alert["id"])
    assert response.status_code == 404
    check(contract, "AlertError", response.json())
    assert response.json()["code"] == "ALERT_NOT_FOUND"
    assert ack(owner, "not-a-uuid").status_code == 404
    assert ack(owner, str(uuid.uuid4())).status_code == 404

    first = ack(owner, alert["id"])
    assert first.status_code == 200, first.text
    check(contract, "Alert", first.json())
    clock.advance(60)
    second = ack(owner, alert["id"])
    assert second.status_code == 200
    assert second.json()["acknowledgedAt"] == first.json()["acknowledgedAt"]
    assert page(owner, contract)["unread"]["total"] == 0
    assert page(owner, contract, status="unread")["items"] == []
    # The stranger's own alert is untouched.
    assert page(stranger, contract)["items"][0]["acknowledgedAt"] is None


def test_alert_rows_change_only_by_a_first_acknowledgement(client: TestClient) -> None:
    signed_in(client)
    with pytest.raises(sqlalchemy.exc.DBAPIError, match="first acknowledgement"):
        db_rows(_db(), "UPDATE alerts SET title = 'changed'")
    db_rows(_db(), "UPDATE alerts SET acknowledged_at = now()")
    with pytest.raises(sqlalchemy.exc.DBAPIError, match="first acknowledgement"):
        db_rows(_db(), "UPDATE alerts SET acknowledged_at = now() + interval '1 day'")
    # Deleting the user cascades.
    db_rows(_db(), "DELETE FROM users")
    assert db_rows(_db(), "SELECT count(*) AS n FROM alerts") == [{"n": 0}]


# ----------------------------------------------------------- pages and filters


def test_pages_are_stable_complete_and_isolated(client: TestClient, contract: Any) -> None:
    owner = signed_in(client)
    stranger = signed_in(client, phone=OTHER_PHONE)
    uid = user_id(owner)
    insert_alerts(uid, 23)
    insert_alerts(uid, 4, kind="PAPER_ENGINE_HALTED")
    first = page(owner, contract, limit=10)
    insert_alerts(uid, 3)  # arrives while paging
    rest = every_alert(owner, contract, limit=10, cursor=first["nextCursor"])
    seen = first["items"] + rest
    assert len(seen) == 28  # 27 inserted before the first page, plus the sign-in
    assert len({a["id"] for a in seen}) == 28
    assert len(every_alert(owner, contract, limit=100)) == 31
    assert kinds(every_alert(stranger, contract)) == ["NEW_SIGN_IN"]

    critical = every_alert(owner, contract, severity="critical", limit=3)
    assert kinds(critical) == ["PAPER_ENGINE_HALTED"] * 4
    both = every_alert(owner, contract, severity=["critical", "info"], source="paper")
    assert len(both) == 30


def test_acknowledging_while_paging_unread_skips_nothing(client: TestClient, contract: Any) -> None:
    browser = signed_in(client)
    insert_alerts(user_id(browser), 9)
    first = page(browser, contract, status="unread", limit=4)
    for alert in first["items"]:
        assert ack(browser, alert["id"]).status_code == 200
    rest = every_alert(browser, contract, status="unread", limit=4, cursor=first["nextCursor"])
    ids = [a["id"] for a in first["items"] + rest]
    assert len(ids) == 10
    assert len(set(ids)) == 10


@pytest.mark.parametrize(
    "params",
    [
        {"severity": "urgent"},
        {"source": "markets"},
        {"status": "read"},
        {"limit": 0},
        {"limit": 101},
        {"severity": ["info", "info"]},
        {"cursor": "!!!"},
        {"cursor": base64.urlsafe_b64encode(b"v1:0000000000000000:5").decode().rstrip("=")},
    ],
)
def test_invalid_queries_are_400(client: TestClient, contract: Any, params: Any) -> None:
    browser = signed_in(client)
    response = browser.get(ALERTS, params=params)
    assert response.status_code == 400, response.text
    check(contract, "AlertError", response.json())
    assert response.json()["code"] == "INVALID_REQUEST"


def test_cursor_is_bound_to_its_filters(client: TestClient, contract: Any) -> None:
    browser = signed_in(client)
    insert_alerts(user_id(browser), 5)
    cursor = page(browser, contract, limit=2)["nextCursor"]
    assert cursor is not None
    assert browser.get(ALERTS, params={"limit": 2, "cursor": cursor}).status_code == 200
    for params in ({"source": "paper"}, {"status": "unread"}, {"severity": "info"}):
        response = browser.get(ALERTS, params={**params, "cursor": cursor})
        assert response.status_code == 400, params


# ---------------------------------------------------------------- preferences


def test_preferences_hide_optional_alerts_but_never_critical(
    client: TestClient, clock: FakeClock, contract: Any
) -> None:
    browser = signed_in(client)
    uid = user_id(browser)
    insert_alerts(uid, 2, kind="PAPER_ENGINE_HALTED")
    insert_alerts(uid, 3, kind="PAPER_STOP_LOSS_EXIT")
    defaults = browser.get(PREFS)
    assert defaults.status_code == 200
    check(contract, "AlertPreferences", defaults.json())
    assert defaults.json()["inApp"] == {"critical": True, "warning": True, "info": True}
    assert [c["channel"] for c in defaults.json()["channels"]] == ["email", "sms", "push"]
    assert all(not c["available"] and not c["enabled"] for c in defaults.json()["channels"])
    assert defaults.json()["updatedAt"] is None
    cursor = page(browser, contract, limit=2)["nextCursor"]

    saved = browser.send(
        "PUT", PREFS, json={"inApp": {"warning": False, "info": False}}, headers=browser.headers()
    )
    assert saved.status_code == 200, saved.text
    check(contract, "AlertPreferences", saved.json())
    assert saved.json()["inApp"] == {"critical": True, "warning": False, "info": False}
    body = page(browser, contract)
    assert kinds(body["items"]) == ["PAPER_ENGINE_HALTED"] * 2
    assert body["unread"] == {"total": 2, "critical": 2, "warning": 0, "info": 0}
    # Asking for a hidden severity explicitly still leaves it out.
    assert page(browser, contract, severity="warning")["items"] == []
    # A cursor issued under other preferences is rejected.
    assert browser.get(ALERTS, params={"limit": 2, "cursor": cursor}).status_code == 400

    clock.advance(60)
    again = browser.send(
        "PUT", PREFS, json={"inApp": {"warning": False, "info": False}}, headers=browser.headers()
    )
    assert again.json()["updatedAt"] == saved.json()["updatedAt"]
    restored = browser.send(
        "PUT", PREFS, json={"inApp": {"warning": True, "info": True}}, headers=browser.headers()
    )
    assert restored.status_code == 200
    assert len(every_alert(browser, contract)) == 6  # hidden alerts were kept
    audits = db_rows(
        _db(), "SELECT metadata_redacted FROM audit_events WHERE action = 'alerts.preferences'"
    )
    assert len(audits) == 2  # the repeated save changed nothing


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"inApp": {"warning": True}},
        {"inApp": {"warning": "yes", "info": True}},
        {"inApp": {"warning": True, "info": True, "critical": False}},
        {"inApp": {"warning": True, "info": True}, "email": True},
    ],
)
def test_malformed_preferences_are_400(client: TestClient, contract: Any, body: Any) -> None:
    browser = signed_in(client)
    response = browser.send("PUT", PREFS, json=body, headers=browser.headers())
    assert response.status_code == 400, response.text
    assert response.json()["code"] == "INVALID_REQUEST"
    assert browser.get(PREFS).json()["updatedAt"] is None


def test_every_contract_alert_operation_is_implemented(client: TestClient, contract: Any) -> None:
    implemented = client.get("/openapi.json").json()["paths"]
    for path, operations in contract["paths"].items():
        if path.startswith(ALERTS):
            assert path in implemented, path
            for method, spec in operations.items():
                assert implemented[path][method]["operationId"] == spec["operationId"]


# ------------------------------------------------------------------ migration


def test_alert_migration_rolls_back_and_forward(db_url: str) -> None:
    cfg = _alembic(db_url)
    # Representative data at 0008: a user with a paper account and an agent event.
    db_rows(
        db_url,
        "INSERT INTO users (phone_e164, created_at, updated_at)"
        " VALUES ('+919000000001', now(), now())",
    )
    command.downgrade(cfg, "0008")
    assert db_rows(db_url, "SELECT to_regclass('alerts') AS t") == [{"t": None}]
    assert db_rows(db_url, "SELECT count(*) AS n FROM users") == [{"n": 1}]
    command.upgrade(cfg, "head")
    assert db_rows(db_url, "SELECT count(*) AS n FROM alerts") == [{"n": 0}]
    assert db_rows(db_url, "SELECT count(*) AS n FROM users") == [{"n": 1}]


def test_concurrent_acknowledgements_agree(client: TestClient, contract: Any) -> None:
    import asyncio

    browser = signed_in(client)
    (alert,) = page(browser, contract)["items"]
    uid = uuid.UUID(user_id(browser))
    service: AlertService = client.app.state.alerts  # type: ignore[attr-defined]

    async def both() -> list[Any]:
        return list(
            await asyncio.gather(*(service.acknowledge(uid, alert["id"]) for _ in range(5)))
        )

    assert client.portal is not None
    results = client.portal.call(both)
    assert len({r.acknowledged_at for r in results}) == 1
    assert results[0].acknowledged_at is not None


def test_recording_one_occurrence_twice_keeps_one_alert(client: TestClient) -> None:
    from app.alerts import producer

    browser = signed_in(client)
    uid = uuid.UUID(user_id(browser))
    factory = client.app.state.session_factory  # type: ignore[attr-defined]
    at = FakeClock()()

    async def record_twice() -> None:
        for _ in range(2):
            async with factory() as db, db.begin():
                await producer.record(
                    db,
                    user_id=uid,
                    kind="PAPER_ENGINE_HALTED",
                    dedupe_key="paper-halted:retry",
                    message="Kill switch.",
                    at=at,
                )

    assert client.portal is not None
    client.portal.call(record_twice)
    rows = db_rows(
        _db(), "SELECT count(*) AS n FROM alerts WHERE dedupe_key = 'paper-halted:retry'"
    )
    assert rows == [{"n": 1}]


def test_worker_records_a_batch_of_occurrences(client: TestClient, clock: FakeClock) -> None:
    """Two expired connections and two mismatch events in one pass all persist;
    a retry records nothing."""
    browser = signed_in(client)
    uid = user_id(browser)
    for provider in ("zerodha", "fyers"):
        response = browser.post(f"{BROKERS}/{provider}/actions", json={"action": "connect"})
        assert response.status_code == 200, response.text
    for key in ("m1", "m2"):
        db_rows(
            _db(),
            "INSERT INTO agent_events (user_id, agent_id, dedupe_key, reason_code, severity,"
            " message, data_as_of, created_at) VALUES (:u, 'execution-monitor', :k,"
            " 'RECONCILIATION_MISMATCH', 'warning', 'The ledger does not match.', now(), now())",
            u=uid,
            k=key,
        )
    clock.advance(8 * 3600)
    assert worker(client) == 4
    assert worker(client) == 0
    rows = db_rows(_db(), "SELECT count(DISTINCT id) AS n FROM alerts WHERE kind <> 'NEW_SIGN_IN'")
    assert rows == [{"n": 4}]


def test_an_alert_rolls_back_with_its_source_transaction(client: TestClient) -> None:
    from app.alerts import producer

    browser = signed_in(client)
    uid = uuid.UUID(user_id(browser))
    factory = client.app.state.session_factory  # type: ignore[attr-defined]
    at = FakeClock()()

    async def record(fail: bool) -> None:
        async with factory() as db, db.begin():
            await producer.record(
                db,
                user_id=uid,
                kind="PAPER_ENGINE_HALTED",
                dedupe_key="paper-halted:rollback",
                message="Kill switch.",
                at=at,
            )
            if fail:
                raise RuntimeError("the source change failed")

    count = "SELECT count(*) AS n FROM alerts WHERE dedupe_key = 'paper-halted:rollback'"
    assert client.portal is not None
    with pytest.raises(RuntimeError):
        client.portal.call(record, True)
    assert db_rows(_db(), count) == [{"n": 0}]
    client.portal.call(record, False)
    assert db_rows(_db(), count) == [{"n": 1}]
