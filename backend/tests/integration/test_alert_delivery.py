"""Email, SMS and push alert delivery (contract 0.13.0) over real Postgres and
Redis, with the simulated (log) provider and an injected failing one."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import jsonschema
import pytest
import yaml  # type: ignore[import-untyped]
from alembic import command
from fastapi.testclient import TestClient

from app.alerts.delivery import Notification, NotificationDeliveryError
from app.alerts.delivery_service import AlertDeliveryService
from app.retention.service import RetentionService
from tests.integration.test_paper import CONTRACT_PATH, _alembic, check
from tests.support import PHONE, Browser, FakeClock, db_rows, invite_phone

pytestmark = pytest.mark.integration

PREFS = "/api/v1/alerts/preferences"
CHANNELS = "/api/v1/alerts/channels"
DELIVERIES = "/api/v1/alerts/deliveries"


def db() -> str:
    return os.environ["TEST_DATABASE_URL"]


@pytest.fixture
def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


SIMULATED = {
    "notify_email_provider": "log",
    "notify_sms_provider": "log",
    "notify_push_provider": "log",
}


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    return make_app(
        paper_worker_enabled=False,
        backtest_worker_enabled=False,
        agent_worker_enabled=False,
        alert_worker_enabled=False,
        **SIMULATED,
    )


@pytest.fixture
def user(client: TestClient, clock: FakeClock) -> Browser:
    browser = Browser(client)
    browser.login_ready()
    clock.advance(1)  # the sign-in alert predates any channel enabled below
    return browser


def service(client: TestClient) -> AlertDeliveryService:
    svc: AlertDeliveryService = client.app.state.alert_delivery  # type: ignore[attr-defined]
    return svc


def run(client: TestClient) -> int:
    assert client.portal is not None
    sent: int = client.portal.call(service(client).run_once)
    return sent


def uid(browser: Browser) -> str:
    value: str = browser.get("/api/v1/auth/me").json()["user"]["id"]
    return value


def body(**channels: tuple[bool, str]) -> dict[str, Any]:
    full = {"email": (False, "critical"), "sms": (False, "critical"), "push": (False, "critical")}
    full.update(channels)
    return {
        "channels": [{"channel": c, "enabled": e, "minSeverity": m} for c, (e, m) in full.items()]
    }


def save(browser: Browser, payload: Any, **kw: Any) -> Any:
    return browser.send(
        "PUT", CHANNELS, json=payload, headers=kw.pop("headers", browser.headers()), **kw
    )


def add_alert(user_id: str, at: Any, severity: str = "critical") -> str:
    kind = {
        "critical": "PAPER_ENGINE_HALTED",
        "warning": "PAPER_STOP_LOSS_EXIT",
        "info": "PAPER_REPLAY_FINISHED",
    }[severity]
    rows = db_rows(
        db(),
        "INSERT INTO alerts (user_id, dedupe_key, kind, source, severity, environment, title,"
        " message, occurred_at, created_at) VALUES (:u, :k, :kind, 'paper', :s, 'PAPER',"
        " 'Synthetic', 'synthetic message', :t, :t) RETURNING id::text AS id",
        u=user_id,
        k=f"test:{uuid.uuid4()}",
        kind=kind,
        s=severity,
        t=at,
    )
    return str(rows[0]["id"])


def deliveries(browser: Browser, contract: dict[str, Any]) -> list[dict[str, Any]]:
    response = browser.get(DELIVERIES)
    assert response.status_code == 200, response.text
    check(contract, "AlertDeliveryList", response.json())
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def code_of(response: Any) -> str:
    return str(response.json()["code"])


class Failing:
    configured = True
    simulated = False

    def __init__(self) -> None:
        self.calls = 0

    async def send(self, notification: Notification) -> None:
        self.calls += 1
        raise NotificationDeliveryError("down")


def test_channels_report_availability_and_masked_destinations(
    user: Browser, contract: dict[str, Any]
) -> None:
    response = user.get(PREFS)
    assert response.status_code == 200
    check(contract, "AlertPreferences", response.json())
    channels = {c["channel"]: c for c in response.json()["channels"]}
    assert channels["sms"] == {
        "channel": "sms",
        "available": True,
        "unavailableReason": None,
        "enabled": False,
        "minSeverity": "critical",
        "destinationMasked": "+91******3210",
    }
    assert channels["email"]["unavailableReason"] == "NO_DESTINATION"
    assert channels["push"]["unavailableReason"] == "NO_DESTINATION"
    invite_phone(PHONE, email="avi@example.com")
    email = {c["channel"]: c for c in user.get(PREFS).json()["channels"]}["email"]
    assert email["available"] and email["destinationMasked"] == "a***@example.com"


def test_unconfigured_providers_are_unavailable(make_app: Callable[..., TestClient]) -> None:
    client = make_app(alert_worker_enabled=False)
    browser = Browser(client)
    browser.login_ready()
    channels = browser.get(PREFS).json()["channels"]
    assert {c["unavailableReason"] for c in channels} == {"PROVIDER_NOT_CONFIGURED"}
    refused = save(browser, body(sms=(True, "critical")))
    assert (refused.status_code, code_of(refused)) == (409, "ALERT_CHANNEL_UNAVAILABLE")


def test_save_channels_is_audited_and_validated(user: Browser, contract: dict[str, Any]) -> None:
    saved = save(user, body(sms=(True, "warning")))
    assert saved.status_code == 200, saved.text
    check(contract, "AlertPreferences", saved.json())
    sms = {c["channel"]: c for c in saved.json()["channels"]}["sms"]
    assert sms["enabled"] and sms["minSeverity"] == "warning"
    assert save(user, body(sms=(True, "warning"))).status_code == 200  # no change
    audit = db_rows(
        db(), "SELECT metadata_redacted FROM audit_events WHERE action = 'alerts.channels'"
    )
    assert [a["metadata_redacted"] for a in audit] == [
        {
            "before": {"sms": {"enabled": False, "minSeverity": "critical"}},
            "after": {"sms": {"enabled": True, "minSeverity": "warning"}},
        }
    ]
    assert "3210" not in str(audit)

    push = save(user, body(push=(True, "critical")))
    assert (push.status_code, code_of(push)) == (409, "ALERT_CHANNEL_UNAVAILABLE")
    check(contract, "AlertDeliveryError", push.json())
    dup = {"channels": [{"channel": "sms", "enabled": False, "minSeverity": "info"}] * 3}
    assert code_of(save(user, dup)) == "INVALID_REQUEST"
    assert code_of(save(user, {"channels": body()["channels"][:2]})) == "INVALID_REQUEST"
    assert code_of(save(user, body(), headers=user.headers(csrf="x"))) == "CSRF_FAILED"


def test_unavailable_channel_already_enabled_may_stay_enabled(
    user: Browser, contract: dict[str, Any]
) -> None:
    # Push was enabled while it was available and has since become unavailable.
    db_rows(
        db(),
        "INSERT INTO alert_channel_settings (user_id, channel, enabled, min_severity,"
        " enabled_at, updated_at) SELECT id, 'push', true, 'critical', now(), now() FROM users",
    )
    saved = save(user, body(push=(True, "warning")))
    assert saved.status_code == 200, saved.text
    push = {c["channel"]: c for c in saved.json()["channels"]}["push"]
    assert (push["available"], push["enabled"], push["minSeverity"]) == (False, True, "warning")
    # Turning it off is allowed; turning it back on is refused and changes nothing.
    assert save(user, body()).status_code == 200
    refused = save(user, body(sms=(True, "info"), push=(True, "critical")))
    assert (refused.status_code, code_of(refused)) == (409, "ALERT_CHANNEL_UNAVAILABLE")
    check(contract, "AlertDeliveryError", refused.json())
    channels = {c["channel"]: c for c in user.get("/api/v1/alerts/preferences").json()["channels"]}
    assert not channels["sms"]["enabled"] and not channels["push"]["enabled"]


def test_channels_need_one_entry_each_in_the_contract(contract: dict[str, Any]) -> None:
    validator = jsonschema.Draft202012Validator(
        {"$ref": "#/components/schemas/AlertChannelsUpdate", "components": contract["components"]}
    )
    assert validator.is_valid(body())
    dup = {"channels": [{"channel": "sms", "enabled": False, "minSeverity": "info"}] * 3}
    assert not validator.is_valid(dup)


def test_worker_sends_matching_alerts_once(
    client: TestClient, user: Browser, clock: FakeClock, contract: dict[str, Any]
) -> None:
    me = uid(user)
    before = add_alert(me, clock.now - timedelta(seconds=1))  # recorded before enabling
    save(user, body(sms=(True, "warning")))
    clock.advance(5)
    critical = add_alert(me, clock.now, "critical")
    add_alert(me, clock.now, "info")  # below minSeverity
    assert run(client) == 1
    assert run(client) == 0
    (item,) = deliveries(user, contract)
    assert item["alertId"] == critical != before
    assert item["status"] == "sent" and item["simulated"] is True and item["attempts"] == 1
    assert item["destinationMasked"] == "+91******3210" and item["sentAt"] is not None


def test_alerts_older_than_the_lookback_are_not_sent(
    client: TestClient, user: Browser, clock: FakeClock
) -> None:
    save(user, body(sms=(True, "info")))
    add_alert(uid(user), clock.now)
    clock.advance(2 * 3600)  # the worker was down for longer than the lookback
    assert run(client) == 0
    assert db_rows(db(), "SELECT 1 FROM alert_deliveries") == []


def test_disabling_after_enqueue_skips(client: TestClient, user: Browser, clock: FakeClock) -> None:
    save(user, body(sms=(True, "info")))
    add_alert(uid(user), clock.now)
    assert client.portal is not None
    client.portal.call(service(client).enqueue)
    save(user, body())
    assert run(client) == 0
    row = db_rows(db(), "SELECT status, status_reason FROM alert_deliveries")[0]
    assert row == {"status": "skipped", "status_reason": "CHANNEL_DISABLED"}


def test_provider_errors_retry_then_fail(
    client: TestClient, user: Browser, clock: FakeClock
) -> None:
    failing = Failing()
    service(client)._providers["sms"] = failing
    save(user, body(sms=(True, "info")))
    add_alert(uid(user), clock.now)
    run(client)
    row = db_rows(db(), "SELECT status, status_reason, attempts FROM alert_deliveries")[0]
    assert row == {"status": "pending", "status_reason": "PROVIDER_ERROR", "attempts": 1}
    assert run(client) == 0 and failing.calls == 1  # backoff: not due yet
    for _ in range(2):
        clock.advance(16 * 60)
        run(client)
    row = db_rows(db(), "SELECT status, status_reason, attempts FROM alert_deliveries")[0]
    assert row == {"status": "failed", "status_reason": "PROVIDER_ERROR", "attempts": 3}
    clock.advance(3600)
    run(client)
    assert failing.calls == 3


def test_daily_cap_skips(make_app: Callable[..., TestClient], clock: FakeClock) -> None:
    client = make_app(alert_worker_enabled=False, notify_daily_limit_per_channel=1, **SIMULATED)
    browser = Browser(client)
    browser.login_ready()
    clock.advance(1)
    save(browser, body(sms=(True, "info")))
    add_alert(uid(browser), clock.now)
    add_alert(uid(browser), clock.now)
    assert run(client) == 1
    statuses = sorted(
        (r["status"], r["status_reason"])
        for r in db_rows(db(), "SELECT status, status_reason FROM alert_deliveries")
    )
    assert statuses == [("sent", None), ("skipped", "DAILY_LIMIT")]


def _insert_deliveries(user_id: str, now: Any, count: int, kind: str = "test") -> None:
    db_rows(
        db(),
        "INSERT INTO alert_deliveries (user_id, kind, channel, status, attempts, next_attempt_at,"
        " created_at) SELECT :u, :k, 'sms', 'pending', 0, :t, :t FROM generate_series(1, :n)",
        u=user_id,
        k=kind,
        t=now,
        n=count,
    )


def test_daily_cap_counts_the_day_sending_starts(
    make_app: Callable[..., TestClient], clock: FakeClock
) -> None:
    client = make_app(alert_worker_enabled=False, notify_daily_limit_per_channel=1, **SIMULATED)
    browser = Browser(client)
    browser.login_ready()
    clock.advance(1)
    me = uid(browser)
    _insert_deliveries(me, clock.now, 2)  # queued today ...
    clock.advance(20 * 3600)  # ... claimed after midnight UTC
    assert run(client) == 1
    assert sorted(r["status"] for r in db_rows(db(), "SELECT status FROM alert_deliveries")) == [
        "sent",
        "skipped",
    ]


def test_retries_obey_the_daily_cap_too(
    make_app: Callable[..., TestClient], clock: FakeClock
) -> None:
    client = make_app(alert_worker_enabled=False, notify_daily_limit_per_channel=1, **SIMULATED)
    browser = Browser(client)
    browser.login_ready()
    clock.advance(1)
    me = uid(browser)
    _insert_deliveries(me, clock.now, 1)
    db_rows(db(), "UPDATE alert_deliveries SET attempts = 1, last_attempt_at = :t", t=clock.now)
    _insert_deliveries(me, clock.now, 1)  # a second delivery today, over the limit of 1
    db_rows(db(), "UPDATE alert_deliveries SET status = 'sent' WHERE attempts = 1")
    db_rows(db(), "UPDATE alert_deliveries SET attempts = 1 WHERE status = 'pending'")  # a retry
    assert run(client) == 0
    assert db_rows(db(), "SELECT status_reason FROM alert_deliveries WHERE status = 'skipped'") == [
        {"status_reason": "DAILY_LIMIT"}
    ]


def test_concurrent_claims_cannot_exceed_the_daily_cap(
    make_app: Callable[..., TestClient], clock: FakeClock
) -> None:
    client = make_app(alert_worker_enabled=False, notify_daily_limit_per_channel=1, **SIMULATED)
    browser = Browser(client)
    browser.login_ready()
    clock.advance(1)
    _insert_deliveries(uid(browser), clock.now, 120)  # more than one claim batch
    svc = service(client)

    async def both() -> list[Any]:
        return list(await asyncio.gather(svc._claim(), svc._claim()))

    assert client.portal is not None
    first, second = client.portal.call(both)
    assert len(first) + len(second) == 1


def test_exhausted_delivery_is_failed_not_retried_forever(
    client: TestClient, user: Browser, clock: FakeClock
) -> None:
    _insert_deliveries(uid(user), clock.now, 1)
    db_rows(db(), "UPDATE alert_deliveries SET attempts = 3")  # last attempt was interrupted
    _insert_deliveries(uid(user), clock.now, 1)
    assert run(client) == 1  # the healthy one still goes out
    statuses = sorted(r["status"] for r in db_rows(db(), "SELECT status FROM alert_deliveries"))
    assert statuses == ["failed", "sent"]
    assert run(client) == 0


def test_orphaned_alert_delivery_is_skipped_not_sent_as_a_test(
    client: TestClient, user: Browser, clock: FakeClock
) -> None:
    save(user, body(sms=(True, "info")))
    add_alert(uid(user), clock.now)
    assert client.portal is not None
    client.portal.call(service(client).enqueue)
    db_rows(db(), "DELETE FROM alerts WHERE source = 'paper'")  # alert_id becomes NULL
    assert run(client) == 0
    row = db_rows(db(), "SELECT status, status_reason FROM alert_deliveries")[0]
    assert row == {"status": "skipped", "status_reason": "CHANNEL_DISABLED"}


def test_long_invite_email_is_masked_and_sent(
    client: TestClient, user: Browser, clock: FakeClock
) -> None:
    long_email = "a@" + "d" * 59 + "." + "e" * 60 + ".example.com"
    invite_phone(PHONE, email=long_email)
    db_rows(db(), "UPDATE invites SET email = :e", e=long_email)
    simulated = service(client)._providers
    assert simulated["email"].configured
    save(user, body(email=(True, "info")))
    add_alert(uid(user), clock.now)
    assert run(client) == 1
    row = db_rows(db(), "SELECT status, destination_masked FROM alert_deliveries")[0]
    assert row["status"] == "sent" and len(row["destination_masked"]) > 64


def test_test_messages(client: TestClient, user: Browser, contract: dict[str, Any]) -> None:
    queued = user.post(f"{CHANNELS}/sms/test")
    assert queued.status_code == 202, queued.text
    check(contract, "AlertDelivery", queued.json())
    assert queued.json()["kind"] == "test" and queued.json()["status"] == "pending"
    assert run(client) == 1
    assert deliveries(user, contract)[0]["status"] == "sent"
    user.post(f"{CHANNELS}/sms/test")
    user.post(f"{CHANNELS}/sms/test")
    limited = user.post(f"{CHANNELS}/sms/test")
    assert (limited.status_code, code_of(limited)) == (429, "RATE_LIMITED")
    check(contract, "AlertDeliveryError", limited.json())
    assert int(limited.headers["Retry-After"]) >= 1
    push = user.post(f"{CHANNELS}/push/test")
    assert (push.status_code, code_of(push)) == (409, "ALERT_CHANNEL_UNAVAILABLE")
    assert user.post(f"{CHANNELS}/fax/test").status_code == 400


def test_deliveries_are_per_user(
    client: TestClient, user: Browser, contract: dict[str, Any]
) -> None:
    user.post(f"{CHANNELS}/sms/test")
    other = Browser(client)
    other.login_ready(phone="+918765432109")
    assert deliveries(other, contract) == []


def test_retention_purges_deliveries(client: TestClient, user: Browser, clock: FakeClock) -> None:
    user.post(f"{CHANNELS}/sms/test")
    db_rows(db(), "UPDATE alert_deliveries SET created_at = :t", t=clock.now - timedelta(days=400))
    assert client.portal is not None
    retention: RetentionService = client.app.state.retention  # type: ignore[attr-defined]
    totals = client.portal.call(retention.purge_all)
    assert totals["alertDeliveries"] == 1


def test_purging_an_alert_keeps_its_delivery_record(
    client: TestClient, user: Browser, clock: FakeClock
) -> None:
    save(user, body(sms=(True, "info")))
    alert_id = add_alert(uid(user), clock.now)
    run(client)
    db_rows(db(), "DELETE FROM alerts WHERE id = :i", i=uuid.UUID(alert_id))
    assert db_rows(db(), "SELECT alert_id FROM alert_deliveries") == [{"alert_id": None}]


def test_migration_0018_round_trips(db_url: str, user: Browser) -> None:
    user.post(f"{CHANNELS}/sms/test")
    command.downgrade(_alembic(db_url), "0017")
    assert db_rows(db_url, "SELECT 1 FROM pg_tables WHERE tablename = 'alert_deliveries'") == []
    command.upgrade(_alembic(db_url), "head")
    assert db_rows(db_url, "SELECT 1 FROM pg_tables WHERE tablename = 'alert_deliveries'")
