"""Phase B2 demo broker endpoints over real PostgreSQL and Redis."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from app.brokers.adapter import (
    AccountData,
    AccountGrant,
    BrokerId,
    BrokerUnavailableError,
    DemoBrokerAdapter,
)
from app.core.config import Settings
from app.main import create_app
from tests.conftest import SettingsFactory
from tests.support import OTHER_PHONE, Browser, FakeClock, FixedOtpProvider, db_rows

pytestmark = pytest.mark.integration

BASE = "/api/v1/brokers/preview"
CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"
BACKEND_DIR = Path(__file__).resolve().parents[2]


def act(browser: Browser, provider: str, action: str, **kwargs: Any) -> Any:
    return browser.post(f"{BASE}/{provider}/actions", json={"action": action}, **kwargs)


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def account(snapshot: dict[str, Any], provider: str) -> Any:
    (entry,) = [c for c in snapshot["connections"] if c["provider"] == provider]
    return entry["account"]


@pytest.fixture
def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


def check(contract: dict[str, Any], schema_name: str, payload: Any) -> None:
    schema = {"$ref": f"#/components/schemas/{schema_name}", "components": contract["components"]}
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    errors = list(validator.iter_errors(payload))
    assert not errors, [e.message for e in errors]


@pytest.fixture
def make_broker_app(
    make_settings: SettingsFactory, provider: FixedOtpProvider, clock: FakeClock, db_url: str
) -> Any:
    clients: list[TestClient] = []

    def make(adapter: Any = None, **overrides: Any) -> Browser:
        overrides.setdefault("otp_resend_cooldown_seconds", 0)
        import os

        settings: Settings = make_settings(
            database_url=db_url, redis_url=os.environ["TEST_REDIS_URL"], **overrides
        )
        client = TestClient(
            create_app(settings, otp_provider=provider, clock=clock, broker_adapter=adapter),
            base_url="https://testserver",
        )
        client.__enter__()
        clients.append(client)
        return Browser(client)

    yield make
    for client in reversed(clients):
        client.__exit__(None, None, None)


@pytest.fixture
def long_session(make_app: Callable[..., TestClient]) -> Browser:
    """A session whose idle expiry outlasts the 8-hour demo connection."""
    return Browser(make_app(session_idle_ttl_seconds=86_400))


# ------------------------------------------------------------------ auth and CSRF


def test_requires_a_session(browser: Browser) -> None:
    response = browser.get(BASE)
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    assert response.json()["requestId"]
    # 401 comes before the CSRF check on writes.
    browser.get_csrf()
    assert act(browser, "zerodha", "connect").status_code == 401


def test_write_requires_session_csrf_token(browser: Browser) -> None:
    browser.login()
    missing = act(browser, "zerodha", "connect", headers=browser.headers(csrf=""))
    assert missing.status_code == 403
    assert missing.json()["code"] == "CSRF_FAILED"
    wrong_origin = act(
        browser, "zerodha", "connect", headers=browser.headers(origin="https://evil.example")
    )
    assert wrong_origin.status_code == 403
    assert db_rows(_db(), "SELECT 1 FROM broker_events") == []


def test_token_from_another_session_is_rejected(make_app: Callable[..., TestClient]) -> None:
    client = make_app()
    first, second = Browser(client), Browser(client)
    first.login()
    second.login(phone=OTHER_PHONE)
    response = act(second, "zerodha", "connect", headers=second.headers(csrf=first.csrf))
    assert response.status_code == 403


# ---------------------------------------------------------------------- behavior


def test_new_user_starts_disconnected(browser: Browser, clock: FakeClock, contract: Any) -> None:
    browser.login()
    response = browser.get(BASE)
    assert response.status_code == 200
    body = response.json()
    check(contract, "BrokerResult", body)
    assert body["status"] == "ready"
    data = body["data"]
    assert data["source"] == "demo" and data["environment"] == "DEMO"
    assert parse(data["asOf"]) == clock.now
    assert data["connections"] == [
        {"provider": "zerodha", "account": None},
        {"provider": "fyers", "account": None},
    ]
    assert data["events"] == []


def test_full_lifecycle(browser: Browser, clock: FakeClock, contract: Any) -> None:
    browser.login()
    connected = act(browser, "zerodha", "connect")
    assert connected.status_code == 200, connected.text
    snap = connected.json()
    check(contract, "BrokerSnapshot", snap)
    acc = account(snap, "zerodha")
    assert acc["maskedAccountId"] == "•••• 4821"
    assert parse(acc["connectedAt"]) == clock.now
    assert parse(acc["expiresAt"]) == clock.now + timedelta(hours=8)
    assert acc["lastSyncedAt"] is None
    assert acc["scopes"] == ["profile_read", "holdings_read", "orders_read"]
    assert account(snap, "fyers") is None

    clock.advance(60)
    synced = act(browser, "zerodha", "sync").json()
    assert parse(account(synced, "zerodha")["lastSyncedAt"]) == clock.now

    clock.advance(60)
    gone = act(browser, "zerodha", "disconnect").json()
    check(contract, "BrokerSnapshot", gone)
    assert account(gone, "zerodha") is None
    assert [(e["provider"], e["action"]) for e in gone["events"]] == [
        ("zerodha", "connect"),
        ("zerodha", "sync"),
        ("zerodha", "disconnect"),
    ]
    assert len({e["id"] for e in gone["events"]}) == 3
    # The GET shows the same state.
    assert browser.get(BASE).json()["data"]["events"] == gone["events"]

    audit = db_rows(_db(), "SELECT action, resource FROM audit_events WHERE action LIKE 'broker.%'")
    assert [(r["action"], r["resource"]) for r in audit] == [
        ("broker.connect", "broker:zerodha"),
        ("broker.sync", "broker:zerodha"),
        ("broker.disconnect", "broker:zerodha"),
    ]


@pytest.mark.parametrize(
    ("setup", "action"),
    [
        ([], "sync"),
        ([], "reconnect"),
        ([], "disconnect"),
        (["connect"], "connect"),
        (["connect"], "reconnect"),
    ],
)
def test_actions_that_do_not_fit_the_state_conflict(
    browser: Browser, setup: list[str], action: str
) -> None:
    browser.login()
    for step in setup:
        assert act(browser, "fyers", step).status_code == 200
    before = db_rows(_db(), "SELECT count(*) AS n FROM broker_events")[0]["n"]
    response = act(browser, "fyers", action)
    assert response.status_code == 409
    assert response.json()["code"] == "BROKER_ACTION_CONFLICT"
    assert db_rows(_db(), "SELECT count(*) AS n FROM broker_events")[0]["n"] == before


def test_expired_connection_can_only_reconnect_or_disconnect(
    long_session: Browser, clock: FakeClock
) -> None:
    browser = long_session
    browser.login()
    act(browser, "zerodha", "connect")
    act(browser, "zerodha", "sync")
    clock.advance(8 * 3600)  # exactly at expiresAt: expired
    assert act(browser, "zerodha", "sync").status_code == 409
    assert act(browser, "zerodha", "connect").status_code == 409
    renewed = act(browser, "zerodha", "reconnect")
    assert renewed.status_code == 200
    acc = account(renewed.json(), "zerodha")
    assert acc["lastSyncedAt"] is None
    assert parse(acc["expiresAt"]) == clock.now + timedelta(hours=8)
    assert len(db_rows(_db(), "SELECT 1 FROM broker_connections")) == 1


def test_expired_connection_can_disconnect(long_session: Browser, clock: FakeClock) -> None:
    browser = long_session
    browser.login()
    act(browser, "fyers", "connect")
    clock.advance(9 * 3600)
    assert act(browser, "fyers", "disconnect").status_code == 200
    assert db_rows(_db(), "SELECT 1 FROM broker_connections") == []


@pytest.mark.parametrize(
    ("broker", "body"),
    [
        ("upstox", {"action": "connect"}),
        ("zerodha", {"action": "place_order"}),
        ("zerodha", {}),
        ("zerodha", {"action": "connect", "extra": 1}),
    ],
)
def test_invalid_requests_are_400(browser: Browser, broker: str, body: Any) -> None:
    browser.login()
    response = browser.post(f"{BASE}/{broker}/actions", json=body)
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"


def test_users_only_see_their_own_connections(make_app: Callable[..., TestClient]) -> None:
    client = make_app()
    first, second = Browser(client), Browser(client)
    first.login()
    second.login(phone=OTHER_PHONE)
    assert act(first, "zerodha", "connect").status_code == 200
    other = second.get(BASE).json()["data"]
    assert account(other, "zerodha") is None
    assert other["events"] == []
    # And the second user's actions do not touch the first user's state.
    assert act(second, "zerodha", "connect").status_code == 200
    assert act(second, "zerodha", "disconnect").status_code == 200
    assert account(first.get(BASE).json()["data"], "zerodha") is not None


def test_events_are_capped_at_50_oldest_first(browser: Browser, clock: FakeClock) -> None:
    browser.login()
    act(browser, "zerodha", "connect")
    for _ in range(51):
        clock.advance(1)
        assert act(browser, "zerodha", "sync").status_code == 200
    events = browser.get(BASE).json()["data"]["events"]
    assert len(events) == 50
    assert all(e["action"] == "sync" for e in events)  # the connect fell off
    times = [parse(e["at"]) for e in events]
    assert times == sorted(times) and times[-1] == clock.now


def test_concurrent_connects_create_one_connection(client: TestClient) -> None:
    browser = Browser(client)
    browser.login()
    active = browser.activate()
    headers = {
        **browser.headers(),
        "Cookie": "; ".join(f"{c.name}={c.value}" for c in browser.jar.jar),
    }
    active.cookies.clear()

    def attempt(_: int) -> int:
        response = active.post(
            f"{BASE}/zerodha/actions", json={"action": "connect"}, headers=headers
        )
        return int(response.status_code)

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, range(8)))
    assert statuses.count(200) == 1
    assert statuses.count(409) == 7
    assert len(db_rows(_db(), "SELECT 1 FROM broker_connections")) == 1
    assert len(db_rows(_db(), "SELECT 1 FROM broker_events")) == 1


# ------------------------------------------------------------- source failures


class FailingAdapter(DemoBrokerAdapter):
    async def authorize(self, provider: BrokerId, now: datetime) -> AccountGrant:
        raise BrokerUnavailableError("down")


class SlowAdapter(DemoBrokerAdapter):
    async def authorize(self, provider: BrokerId, now: datetime) -> AccountGrant:
        await asyncio.sleep(1)
        return await super().authorize(provider, now)


class WrongAccountAdapter(DemoBrokerAdapter):
    async def fetch_account(self, provider: BrokerId, masked_account_id: str) -> AccountData:
        return AccountData(masked_account_id="•••• 0000", holdings_count=0, open_orders_count=0)


@pytest.mark.parametrize("adapter", [FailingAdapter(), SlowAdapter()])
def test_source_failure_is_503_and_writes_nothing(make_broker_app: Any, adapter: Any) -> None:
    browser = make_broker_app(adapter, broker_timeout_seconds=0.1)
    browser.login()
    response = act(browser, "zerodha", "connect")
    assert response.status_code == 503
    assert response.json()["code"] == "BROKER_UNAVAILABLE"
    assert db_rows(_db(), "SELECT 1 FROM broker_connections") == []
    assert db_rows(_db(), "SELECT 1 FROM broker_events") == []
    assert db_rows(_db(), "SELECT 1 FROM audit_events WHERE action LIKE 'broker.%'") == []


def test_sync_for_a_different_account_is_not_recorded(make_broker_app: Any) -> None:
    browser = make_broker_app(WrongAccountAdapter())
    browser.login()
    assert act(browser, "zerodha", "connect").status_code == 200
    response = act(browser, "zerodha", "sync")
    assert response.status_code == 503
    assert account(browser.get(BASE).json()["data"], "zerodha")["lastSyncedAt"] is None


def test_disabled_provider_is_503(make_broker_app: Any) -> None:
    browser = make_broker_app(broker_provider="disabled")
    browser.login()
    for response in (browser.get(BASE), act(browser, "zerodha", "connect")):
        assert response.status_code == 503
        assert response.json()["code"] == "BROKER_UNAVAILABLE"


# ---------------------------------------------------------------- contract, DB


def test_every_contract_broker_operation_is_implemented(contract: Any, browser: Browser) -> None:
    served = browser.get("/openapi.json").json()["paths"]
    for path, operations in contract["paths"].items():
        if not path.startswith("/api/v1/brokers/"):
            continue
        assert path in served, f"{path} missing from the API"
        for method in operations:
            assert method in served[path], f"{method.upper()} {path} missing"


def test_error_bodies_match_contract(browser: Browser, contract: Any) -> None:
    check(contract, "BrokerError", browser.get(BASE).json())
    browser.login()
    check(contract, "BrokerError", act(browser, "fyers", "sync").json())


def test_broker_migration_rolls_back_and_forward(db_url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = db_url
    tables = {"broker_connections", "broker_events"}

    def present() -> set[str]:
        rows = db_rows(db_url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {r["tablename"] for r in rows}

    assert tables <= present()
    command.downgrade(cfg, "0002")
    assert not (tables & present())
    assert "users" in present()
    command.upgrade(cfg, "head")
    assert tables <= present()


def test_deleting_a_user_removes_their_broker_rows(browser: Browser) -> None:
    browser.login()
    act(browser, "zerodha", "connect")
    db_rows(_db(), "DELETE FROM users")
    assert db_rows(_db(), "SELECT 1 FROM broker_connections") == []
    assert db_rows(_db(), "SELECT 1 FROM broker_events") == []


def test_database_rejects_non_demo_connections(browser: Browser) -> None:
    browser.login()
    act(browser, "zerodha", "connect")
    with pytest.raises(Exception, match="environment_demo"):
        db_rows(_db(), "UPDATE broker_connections SET environment = 'LIVE'")


def _db() -> str:
    import os

    return os.environ["TEST_DATABASE_URL"]


def test_check_constraints_keep_their_intended_names() -> None:
    """Migration names are final (op.f), not run through the naming convention
    a second time, which would produce ck_<table>_ck_<table>_<name>."""
    rows = db_rows(
        _db(),
        "SELECT conname FROM pg_constraint WHERE contype = 'c'"
        " AND conrelid::regclass::text IN ('broker_connections', 'broker_events')",
    )
    assert {r["conname"] for r in rows} == {
        "ck_broker_connections_provider_valid",
        "ck_broker_connections_environment_demo",
        "ck_broker_connections_expiry_after_connect",
        "ck_broker_events_provider_valid",
        "ck_broker_events_action_valid",
    }


def _connection(provider: str) -> dict[str, Any]:
    return {"provider": provider, "account": None}


@pytest.mark.parametrize(
    "connections",
    [
        [],
        [_connection("zerodha")],
        [_connection("zerodha"), _connection("zerodha")],
        [_connection("fyers"), _connection("zerodha")],
        [_connection("zerodha"), _connection("fyers"), _connection("fyers")],
    ],
)
def test_contract_rejects_wrong_provider_lists(contract: Any, connections: Any) -> None:
    snapshot = {
        "source": "demo",
        "environment": "DEMO",
        "asOf": "2026-11-24T06:00:00Z",
        "connections": connections,
        "events": [],
    }
    with pytest.raises(AssertionError):
        check(contract, "BrokerSnapshot", snapshot)


def test_contract_accepts_both_providers_disconnected_and_rejects_extras(contract: Any) -> None:
    snapshot = {
        "source": "demo",
        "environment": "DEMO",
        "asOf": "2026-11-24T06:00:00Z",
        "connections": [_connection("zerodha"), _connection("fyers")],
        "events": [],
    }
    check(contract, "BrokerSnapshot", snapshot)
    with pytest.raises(AssertionError):
        check(contract, "BrokerSnapshot", {**snapshot, "extra": 1})
    with pytest.raises(AssertionError):
        check(contract, "BrokerResult", {"status": "empty", "data": 123})
