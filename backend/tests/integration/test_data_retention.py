"""Data retention: /api/v1/settings/data-retention and the purge job, over real
Postgres and Redis."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from alembic import command
from fastapi.testclient import TestClient

from app.alerts.service import AlertService
from app.retention.service import RetentionService
from tests.integration.test_paper import CONTRACT_PATH, _alembic, check
from tests.support import OTHER_PHONE, Browser, FakeClock, db_rows

pytestmark = pytest.mark.integration

URL = "/api/v1/settings/data-retention"


def db() -> str:
    return os.environ["TEST_DATABASE_URL"]


@pytest.fixture
def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    return make_app(
        paper_worker_enabled=False,
        backtest_worker_enabled=False,
        agent_worker_enabled=False,
        alert_worker_enabled=False,
    )


def open_step_up(clock: FakeClock) -> None:
    db_rows(db(), "UPDATE sessions SET step_up_until = :t", t=clock.now + timedelta(hours=1))


@pytest.fixture
def user(client: TestClient, clock: FakeClock) -> Browser:
    browser = Browser(client)
    browser.login_ready()
    open_step_up(clock)
    return browser


def uid(browser: Browser) -> str:
    value: str = browser.get("/api/v1/auth/me").json()["user"]["id"]
    return value


def save(browser: Browser, body: Any, **kw: Any) -> Any:
    return browser.send("PUT", URL, json=body, headers=kw.pop("headers", browser.headers()), **kw)


def purge(client: TestClient) -> dict[str, int]:
    assert client.portal is not None
    service: RetentionService = client.app.state.retention  # type: ignore[attr-defined]
    result: dict[str, int] = client.portal.call(service.purge_all)
    return result


def alert_worker(client: TestClient) -> int:
    assert client.portal is not None
    service: AlertService = client.app.state.alerts  # type: ignore[attr-defined]
    recorded: int = client.portal.call(service.run_once)
    return recorded


def add_alert(user_id: str, created_at: Any) -> None:
    db_rows(
        db(),
        "INSERT INTO alerts (user_id, dedupe_key, kind, source, severity, environment, title,"
        " message, occurred_at, created_at) VALUES (:u, :k, 'PAPER_REPLAY_FINISHED', 'paper',"
        " 'info', 'PAPER', 'Paper replay finished', 'synthetic', :t, :t)",
        u=user_id,
        k=f"test:{uuid.uuid4()}",
        t=created_at,
    )


def add_agent_event(user_id: str, created_at: Any, reason: str = "RECONCILIATION_MATCHED") -> None:
    db_rows(
        db(),
        "INSERT INTO agent_events (user_id, agent_id, dedupe_key, reason_code, severity,"
        " message, data_as_of, created_at) VALUES (:u, 'execution-monitor', :k, :r,"
        " 'warning', 'synthetic', :t, :t)",
        u=user_id,
        k=f"test:{uuid.uuid4()}",
        r=reason,
        t=created_at,
    )


def count(table: str, user_id: str) -> int:
    return int(
        db_rows(db(), f"SELECT count(*) AS n FROM {table} WHERE user_id = :u", u=user_id)[0]["n"]
    )


def code_of(response: Any) -> str:
    return str(response.json()["code"])


def test_defaults(user: Browser, contract: dict[str, Any]) -> None:
    response = user.get(URL)
    assert response.status_code == 200, response.text
    body = response.json()
    check(contract, "DataRetentionSettings", body)
    assert body == {
        "retentionDays": 365,
        "defaultDays": 365,
        "bounds": {"minDays": 30, "maxDays": 730},
        "categories": ["alerts", "alertDeliveries", "agentEvents"],
        "lastPurge": None,
        "updatedAt": None,
    }


def test_save_is_audited_once(user: Browser, contract: dict[str, Any]) -> None:
    saved = save(user, {"retentionDays": 90})
    assert saved.status_code == 200, saved.text
    check(contract, "DataRetentionSettings", saved.json())
    assert saved.json()["retentionDays"] == 90 and saved.json()["updatedAt"] is not None
    assert save(user, {"retentionDays": 90}).status_code == 200
    audit = db_rows(
        db(),
        "SELECT metadata_redacted FROM audit_events WHERE action = 'settings.data_retention_updated'",
    )
    assert [a["metadata_redacted"] for a in audit] == [{"before": 365, "after": 90}]
    assert user.get(URL).json()["retentionDays"] == 90


def test_saving_the_default_writes_no_audit(user: Browser) -> None:
    assert save(user, {"retentionDays": 365}).status_code == 200
    assert (
        db_rows(db(), "SELECT 1 FROM audit_events WHERE action = 'settings.data_retention_updated'")
        == []
    )


@pytest.mark.parametrize("days", [29, 731])
def test_out_of_bounds(user: Browser, days: int, contract: dict[str, Any]) -> None:
    response = save(user, {"retentionDays": days})
    assert (response.status_code, code_of(response)) == (400, "DATA_RETENTION_OUT_OF_BOUNDS")
    check(contract, "SettingsError", response.json())
    assert "30" in response.json()["message"] and "730" in response.json()["message"]
    assert user.get(URL).json()["updatedAt"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"retentionDays": 0},
        {"retentionDays": "90"},
        {"retentionDays": 90.5},
        {},
        {"retentionDays": 90, "x": 1},
    ],
)
def test_malformed_bodies(user: Browser, body: Any) -> None:
    response = save(user, body)
    assert (response.status_code, code_of(response)) == (400, "INVALID_REQUEST")


def test_save_needs_step_up_then_csrf_order(user: Browser) -> None:
    db_rows(db(), "UPDATE sessions SET step_up_until = NULL")
    response = save(user, {"retentionDays": 90})
    assert (response.status_code, code_of(response)) == (403, "STEP_UP_REQUIRED")
    response = save(user, {"retentionDays": 90}, headers=user.headers(csrf="bad"))
    assert (response.status_code, code_of(response)) == (403, "CSRF_FAILED")


def test_purge_deletes_only_old_records_of_each_user(
    client: TestClient, user: Browser, clock: FakeClock, contract: dict[str, Any]
) -> None:
    other = Browser(client)
    other.login_ready(phone=OTHER_PHONE)
    me, them = uid(user), uid(other)
    for who in (me, them):
        add_alert(who, clock.now - timedelta(days=40))
        add_alert(who, clock.now - timedelta(days=10))
        add_agent_event(who, clock.now - timedelta(days=40))
    before_alerts = count("alerts", me)
    assert save(user, {"retentionDays": 30}).status_code == 200

    totals = purge(client)
    assert totals == {"alerts": 1, "alertDeliveries": 0, "agentEvents": 1}
    assert count("alerts", me) == before_alerts - 1
    assert count("agent_events", me) == 0
    # The other user keeps the 365-day default.
    assert count("agent_events", them) == 1

    body = user.get(URL).json()
    check(contract, "DataRetentionSettings", body)
    assert body["lastPurge"]["deleted"] == {"alerts": 1, "alertDeliveries": 0, "agentEvents": 1}
    audit = db_rows(
        db(),
        "SELECT user_id::text AS u, metadata_redacted FROM audit_events"
        " WHERE action = 'retention.purged'",
    )
    assert audit == [
        {
            "u": me,
            "metadata_redacted": {
                "retentionDays": 30,
                "deleted": {"alerts": 1, "alertDeliveries": 0, "agentEvents": 1},
            },
        }
    ]
    # Running again deletes nothing and keeps the last purge that did.
    assert purge(client) == {"alerts": 0, "alertDeliveries": 0, "agentEvents": 0}
    assert user.get(URL).json()["lastPurge"] == body["lastPurge"]
    assert len(db_rows(db(), "SELECT 1 FROM audit_events WHERE action = 'retention.purged'")) == 1


def test_lengthening_never_moves_the_watermark_back(
    client: TestClient, user: Browser, clock: FakeClock
) -> None:
    save(user, {"retentionDays": 30})
    purge(client)
    first = db_rows(db(), "SELECT purged_through FROM data_retention")[0]["purged_through"]
    save(user, {"retentionDays": 700})
    purge(client)
    assert db_rows(db(), "SELECT purged_through FROM data_retention")[0]["purged_through"] == first


def test_purged_sources_are_not_alerted_again(
    client: TestClient, user: Browser, clock: FakeClock
) -> None:
    me = uid(user)
    db_rows(
        db(),
        "INSERT INTO data_retention (user_id, purged_through) VALUES (:u, :t)",
        u=me,
        t=clock.now - timedelta(days=30),
    )
    # A mismatch event older than the watermark (its alert was purged) and a newer one.
    add_agent_event(me, clock.now - timedelta(days=31), "RECONCILIATION_MISMATCH")
    add_agent_event(me, clock.now - timedelta(days=1), "RECONCILIATION_MISMATCH")
    assert alert_worker(client) == 1


def test_bounds_come_from_settings(make_app: Callable[..., TestClient], clock: FakeClock) -> None:
    client = make_app(
        data_retention_min_days=7, data_retention_max_days=60, data_retention_default_days=14
    )
    browser = Browser(client)
    browser.login_ready()
    open_step_up(clock)
    assert browser.get(URL).json()["bounds"] == {"minDays": 7, "maxDays": 60}
    assert save(browser, {"retentionDays": 7}).status_code == 200
    assert code_of(save(browser, {"retentionDays": 61})) == "DATA_RETENTION_OUT_OF_BOUNDS"


def test_deleting_a_user_removes_the_row(client: TestClient, user: Browser) -> None:
    save(user, {"retentionDays": 90})
    db_rows(db(), "DELETE FROM users")
    assert db_rows(db(), "SELECT 1 FROM data_retention") == []


def test_migration_0017_round_trips(db_url: str, user: Browser) -> None:
    save(user, {"retentionDays": 90})
    command.downgrade(_alembic(db_url), "0016")
    assert db_rows(db_url, "SELECT 1 FROM pg_tables WHERE tablename = 'data_retention'") == []
    command.upgrade(_alembic(db_url), "head")
    assert db_rows(db_url, "SELECT 1 FROM pg_tables WHERE tablename = 'data_retention'")
