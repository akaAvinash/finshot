"""Provider-neutral broker connections: /api/v1/broker-connections (contract
0.11.0) over real PostgreSQL and Redis. Demo adapter only."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import yaml  # type: ignore[import-untyped]
from alembic import command
from fastapi.testclient import TestClient

from app.brokers import adapter as broker_adapter
from app.brokers.adapter import (
    BrokerAuthInvalidError,
    BrokerMalformedResponseError,
    BrokerRateLimitedError,
    BrokerUnavailableError,
    Capability,
    DemoBrokerAdapter,
    PortfolioData,
)
from app.core.config import Settings
from app.main import create_app
from tests.conftest import SettingsFactory
from tests.integration.test_alerts import worker
from tests.integration.test_paper import CONTRACT_PATH, _alembic, check
from tests.support import OTHER_PHONE, Browser, FakeClock, FixedOtpProvider, db_rows

pytestmark = pytest.mark.integration

BASE = "/api/v1/broker-connections"
LEGACY = "/api/v1/brokers/preview"


class FlakyAdapter(DemoBrokerAdapter):
    """The demo adapter with switchable failures and a revoke log."""

    def __init__(self) -> None:
        self.fail_portfolio: Exception | None = None
        self.fail_exchange: Exception | None = None
        self.fail_revoke = False
        self.revoked: list[tuple[str, str]] = []

    async def exchange(self, provider: str, params: Any, now: datetime) -> Any:
        if self.fail_exchange is not None:
            raise self.fail_exchange
        return await super().exchange(provider, params, now)

    async def fetch_portfolio(
        self, provider: str, account_ref: str, capabilities: Sequence[Capability], now: datetime
    ) -> PortfolioData:
        if self.fail_portfolio is not None:
            raise self.fail_portfolio
        return await super().fetch_portfolio(provider, account_ref, capabilities, now)

    async def revoke(self, provider: str, account_ref: str) -> None:
        self.revoked.append((provider, account_ref))
        if self.fail_revoke:
            raise RuntimeError("provider down")


@pytest.fixture
def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


@pytest.fixture
def adapter() -> FlakyAdapter:
    return FlakyAdapter()


@pytest.fixture
def make_app(
    make_settings: SettingsFactory,
    provider: FixedOtpProvider,
    clock: FakeClock,
    db_url: str,
    adapter: FlakyAdapter,
) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def make(**overrides: Any) -> TestClient:
        overrides.setdefault("otp_resend_cooldown_seconds", 0)
        overrides.setdefault("session_idle_ttl_seconds", 86_400)
        settings: Settings = make_settings(
            database_url=db_url, redis_url=os.environ["TEST_REDIS_URL"], **overrides
        )
        client = TestClient(
            create_app(settings, otp_provider=provider, clock=clock, broker_adapter=adapter),
            base_url="https://testserver",
        )
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in reversed(clients):
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    return make_app()


def open_step_up(clock: FakeClock) -> None:
    db_rows(
        os.environ["TEST_DATABASE_URL"],
        "UPDATE sessions SET step_up_until = :t",
        t=clock.now + timedelta(hours=1),
    )


@pytest.fixture
def user(client: TestClient, clock: FakeClock) -> Browser:
    browser = Browser(client)
    browser.login_ready()
    open_step_up(clock)
    return browser


def db() -> str:
    return os.environ["TEST_DATABASE_URL"]


def start(browser: Browser, **body: Any) -> Any:
    return browser.post(f"{BASE}/authorizations", json=body)


def callback(browser: Browser, state: str, params: dict[str, str]) -> Any:
    return browser.post(f"{BASE}/authorizations/callback", json={"state": state, "params": params})


def state_and_params(authorization: dict[str, Any]) -> tuple[str, dict[str, str]]:
    query = parse_qs(urlparse(authorization["authorizeUrl"]).query)
    params = {k: v[0] for k, v in query.items()}
    return params.pop("state"), params


def connect(browser: Browser, contract: Any, provider: str = "zerodha") -> str:
    """Run both steps for `provider`; returns the connectionId."""
    response = start(browser, providerId=provider)
    assert response.status_code == 201, response.text
    check(contract, "BrokerAuthorization", response.json())
    state, params = state_and_params(response.json())
    done = callback(browser, state, params)
    assert done.status_code == 200, done.text
    check(contract, "BrokerAuthorizationResult", done.json())
    connection_id: str = done.json()["connectionId"]
    return connection_id


def action(browser: Browser, connection_id: str, name: str, **kw: Any) -> Any:
    return browser.post(f"{BASE}/{connection_id}/actions", json={"action": name}, **kw)


def code(response: Any) -> str:
    return str(response.json()["code"])


# ------------------------------------------------------------------ auth order


def test_every_endpoint_requires_a_session(browser: Browser) -> None:
    uid = "00000000-0000-4000-8000-000000000001"
    assert browser.get(BASE).status_code == 401
    assert browser.get(f"{BASE}/{uid}/portfolio").status_code == 401
    browser.get_csrf()
    assert start(browser, providerId="zerodha").status_code == 401
    assert callback(browser, "s" * 20, {}).status_code == 401
    assert action(browser, uid, "sync").status_code == 401


def test_start_check_order_is_csrf_then_step_up_then_validation(
    client: TestClient, clock: FakeClock
) -> None:
    browser = Browser(client)
    browser.login_ready()
    junk = {"junk": 1}
    bad_csrf = browser.send(
        "POST", f"{BASE}/authorizations", json=junk, headers=browser.headers(csrf="wrong")
    )
    assert (bad_csrf.status_code, code(bad_csrf)) == (403, "CSRF_FAILED")
    needs = browser.send("POST", f"{BASE}/authorizations", json=junk, headers=browser.headers())
    assert (needs.status_code, code(needs)) == (403, "STEP_UP_REQUIRED")
    open_step_up(clock)
    invalid = browser.send("POST", f"{BASE}/authorizations", json=junk, headers=browser.headers())
    assert (invalid.status_code, code(invalid)) == (400, "INVALID_REQUEST")


def test_callback_and_actions_need_csrf_but_not_step_up(
    client: TestClient, contract: Any, clock: FakeClock
) -> None:
    browser = Browser(client)
    browser.login_ready()
    open_step_up(clock)
    connection_id = connect(browser, contract)
    db_rows(db(), "UPDATE sessions SET step_up_until = NULL")
    bad = browser.send(
        "POST",
        f"{BASE}/{connection_id}/actions",
        json={"action": "sync"},
        headers=browser.headers(csrf="wrong"),
    )
    assert (bad.status_code, code(bad)) == (403, "CSRF_FAILED")
    assert action(browser, connection_id, "sync").status_code == 200


# ---------------------------------------------------------------- the snapshot


def test_new_user_snapshot_lists_providers_and_no_connections(user: Browser, contract: Any) -> None:
    response = user.get(BASE)
    assert response.status_code == 200, response.text
    body = response.json()
    check(contract, "BrokerConnectionsSnapshot", body)
    assert body["source"] == "demo" and body["environment"] == "DEMO"
    assert {p["id"] for p in body["providers"]} == {"zerodha", "fyers"}
    assert all(p["available"] and p["maxConnections"] == 1 for p in body["providers"])
    assert body["connections"] == [] and body["events"] == []
    assert response.headers["X-Request-ID"]


def test_two_step_flow_connects_and_syncs(user: Browser, contract: Any) -> None:
    connection_id = connect(user, contract)
    snapshot = user.get(BASE).json()
    check(contract, "BrokerConnectionsSnapshot", snapshot)
    (conn,) = snapshot["connections"]
    assert conn["connectionId"] == connection_id
    assert (conn["providerId"], conn["status"], conn["statusReason"]) == (
        "zerodha",
        "connected",
        None,
    )
    assert conn["maskedAccountId"] == "•••• 4821" and conn["lastSyncedAt"] is None
    assert "funds_read" not in conn["capabilities"]
    assert [(e["action"], e["connectionId"]) for e in snapshot["events"]] == [
        ("connect", connection_id)
    ]

    # Before the first sync: empty sections, no funds, no asOf.
    before = user.get(f"{BASE}/{connection_id}/portfolio")
    check(contract, "BrokerPortfolio", before.json())
    assert before.json()["asOf"] is None
    assert (before.json()["holdings"], before.json()["funds"]) == ([], None)

    synced = action(user, connection_id, "sync")
    assert synced.status_code == 200, synced.text
    check(contract, "BrokerConnectionsSnapshot", synced.json())
    assert synced.json()["connections"][0]["lastSyncedAt"] is not None
    assert [e["action"] for e in synced.json()["events"]] == ["connect", "sync"]
    after = user.get(f"{BASE}/{connection_id}/portfolio").json()
    check(contract, "BrokerPortfolio", after)
    assert after["asOf"] == synced.json()["connections"][0]["lastSyncedAt"]
    assert after["holdings"] == [] and after["orders"] == [] and after["funds"] is None


def test_authorize_url_is_a_same_origin_path_and_holds_no_secret(user: Browser) -> None:
    response = start(user, providerId="fyers")
    url = response.json()["authorizeUrl"]
    assert url.startswith("/brokers/callback?")
    state, _ = state_and_params(response.json())
    assert len(state) >= 32
    rows = db_rows(db(), "SELECT state_hash FROM broker_authorizations")
    assert [r["state_hash"] for r in rows] != [state]  # only a hash is stored
    assert len(rows[0]["state_hash"]) == 64


# ------------------------------------------------------------- state handling


def test_state_is_single_use(user: Browser, contract: Any) -> None:
    started = start(user, providerId="zerodha").json()
    state, params = state_and_params(started)
    assert callback(user, state, params).status_code == 200
    again = callback(user, state, params)
    assert (again.status_code, code(again)) == (400, "BROKER_AUTHORIZATION_INVALID")
    assert len(user.get(BASE).json()["connections"]) == 1


def test_state_expires_after_ten_minutes(user: Browser, clock: FakeClock) -> None:
    started = start(user, providerId="zerodha").json()
    assert datetime.fromisoformat(started["expiresAt"].replace("Z", "+00:00")) == (
        clock.now + timedelta(minutes=10)
    )
    clock.advance(10 * 60)
    state, params = state_and_params(started)
    late = callback(user, state, params)
    assert (late.status_code, code(late)) == (400, "BROKER_AUTHORIZATION_INVALID")
    assert user.get(BASE).json()["connections"] == []


def test_state_is_bound_to_the_session(client: TestClient, clock: FakeClock) -> None:
    first = Browser(client)
    first.login_ready()
    second = Browser(client)
    second.login_ready()  # a second session of the same user
    open_step_up(clock)
    state, params = state_and_params(start(first, providerId="zerodha").json())
    foreign = callback(second, state, params)
    assert (foreign.status_code, code(foreign)) == (400, "BROKER_AUTHORIZATION_INVALID")
    assert callback(first, state, params).status_code == 200  # the owner's state is unspent


def test_state_of_another_user_is_invalid(client: TestClient, clock: FakeClock) -> None:
    owner = Browser(client)
    owner.login_ready()
    other = Browser(client)
    other.login_ready(phone=OTHER_PHONE)
    open_step_up(clock)
    state, params = state_and_params(start(owner, providerId="zerodha").json())
    stolen = callback(other, state, params)
    assert (stolen.status_code, code(stolen)) == (400, "BROKER_AUTHORIZATION_INVALID")
    assert other.get(BASE).json()["connections"] == []


def test_unknown_state_and_bad_provider_code(user: Browser) -> None:
    unknown = callback(user, "x" * 32, {"code": "demo-zerodha"})
    assert (unknown.status_code, code(unknown)) == (400, "BROKER_AUTHORIZATION_INVALID")
    state, _ = state_and_params(start(user, providerId="zerodha").json())
    wrong = callback(user, state, {"code": "demo-fyers"})
    assert (wrong.status_code, code(wrong)) == (400, "BROKER_AUTHORIZATION_INVALID")
    # The provider rejected it, so the state is spent.
    retry = callback(user, state, {"code": "demo-zerodha"})
    assert (retry.status_code, code(retry)) == (400, "BROKER_AUTHORIZATION_INVALID")
    assert user.get(BASE).json()["connections"] == []


def test_state_claimed_while_the_exchange_runs_is_refused(
    user: Browser, client: TestClient
) -> None:
    state, params = state_and_params(start(user, providerId="zerodha").json())
    service = client.app.state.broker_connections  # type: ignore[attr-defined]

    def claim_elsewhere() -> None:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(db_rows, db(), "UPDATE broker_authorizations SET used_at = now()").result()

    service._after_exchange = claim_elsewhere
    refused = callback(user, state, params)
    assert (refused.status_code, code(refused)) == (400, "BROKER_AUTHORIZATION_INVALID")
    assert user.get(BASE).json()["connections"] == []


def test_callback_body_is_validated(user: Browser) -> None:
    assert callback(user, "short", {}).status_code == 400
    assert callback(user, "s" * 20, {"a": "x" * 513}).status_code == 400
    too_many = {f"k{i}": "v" for i in range(11)}
    assert callback(user, "s" * 20, too_many).status_code == 400
    extra = user.post(
        f"{BASE}/authorizations/callback", json={"state": "s" * 20, "params": {}, "x": 1}
    )
    assert extra.status_code == 400


# ----------------------------------------------------- limits and re-authorizing


def test_start_validates_the_target(user: Browser, contract: Any) -> None:
    both = start(user, providerId="zerodha", connectionId="00000000-0000-4000-8000-000000000001")
    assert (both.status_code, code(both)) == (400, "INVALID_REQUEST")
    assert start(user).status_code == 400
    unknown = start(user, providerId="nope")
    assert (unknown.status_code, code(unknown)) == (400, "BROKER_PROVIDER_UNAVAILABLE")
    missing = start(user, connectionId="00000000-0000-4000-8000-000000000001")
    assert (missing.status_code, code(missing)) == (404, "BROKER_CONNECTION_NOT_FOUND")


def test_a_second_connection_to_the_provider_is_refused(user: Browser, contract: Any) -> None:
    connect(user, contract, "zerodha")
    limited = start(user, providerId="zerodha")
    assert (limited.status_code, code(limited)) == (409, "BROKER_CONNECTION_LIMIT")
    check(contract, "BrokerConnectionError", limited.json())
    assert start(user, providerId="fyers").status_code == 201  # another provider is fine


def test_reauthorizing_keeps_the_connection_id(
    user: Browser, contract: Any, clock: FakeClock
) -> None:
    connection_id = connect(user, contract)
    assert action(user, connection_id, "sync").status_code == 200
    clock.advance(60)
    started = start(user, connectionId=connection_id)
    assert started.status_code == 201
    state, params = state_and_params(started.json())
    done = callback(user, state, params)
    assert done.status_code == 200
    assert done.json()["connectionId"] == connection_id
    snapshot = done.json()["snapshot"]
    check(contract, "BrokerConnectionsSnapshot", snapshot)
    (conn,) = snapshot["connections"]
    assert conn["lastSyncedAt"] is None  # a new authorization starts unsynced
    assert [e["action"] for e in snapshot["events"]] == ["connect", "sync", "reconnect"]
    assert user.get(f"{BASE}/{connection_id}/portfolio").json()["asOf"] is None


def test_the_same_account_renews_instead_of_adding(
    client: TestClient, contract: Any, user: Browser
) -> None:
    first = connect(user, contract)
    # Lift the limit so a start by providerId is possible, as the pilot may.
    client.app.state.broker_connections._adapter.providers = lambda: tuple(  # type: ignore[attr-defined]
        broker_adapter.ProviderSpec(p.id, p.display_name, p.capabilities, 3)
        for p in DemoBrokerAdapter().providers()
    )
    second = connect(user, contract)
    assert second == first
    assert len(user.get(BASE).json()["connections"]) == 1


# --------------------------------------------------------------------- expiry


def test_connection_expires_with_time(user: Browser, contract: Any, clock: FakeClock) -> None:
    connection_id = connect(user, contract)
    clock.advance(8 * 3600)  # exactly at expiresAt
    snapshot = user.get(BASE).json()
    check(contract, "BrokerConnectionsSnapshot", snapshot)
    (conn,) = snapshot["connections"]
    assert (conn["status"], conn["statusReason"]) == ("expired", "EXPIRED")
    refused = action(user, connection_id, "sync")
    assert (refused.status_code, code(refused)) == (409, "BROKER_ACTION_CONFLICT")
    # Re-authorizing an expired connection works and makes it connected again.
    open_step_up(clock)
    state, params = state_and_params(start(user, connectionId=connection_id).json())
    done = callback(user, state, params)
    assert done.json()["snapshot"]["connections"][0]["status"] == "connected"


def test_worker_records_one_expire_event(
    client: TestClient, contract: Any, user: Browser, clock: FakeClock
) -> None:
    connection_id = connect(user, contract)
    clock.advance(8 * 3600)
    assert worker(client) == 1
    assert worker(client) == 0
    events = [e for e in user.get(BASE).json()["events"] if e["action"] == "expire"]
    assert [e["connectionId"] for e in events] == [connection_id]
    check(contract, "BrokerConnectionEvent", events[0])


def test_provider_invalidating_the_authorization_expires_the_connection(
    user: Browser, contract: Any, adapter: FlakyAdapter
) -> None:
    connection_id = connect(user, contract)
    adapter.fail_portfolio = BrokerAuthInvalidError("logged out")
    refused = action(user, connection_id, "sync")
    assert (refused.status_code, code(refused)) == (409, "BROKER_AUTH_EXPIRED")
    check(contract, "BrokerConnectionError", refused.json())
    snapshot = user.get(BASE).json()  # the status change was kept
    (conn,) = snapshot["connections"]
    assert (conn["status"], conn["statusReason"]) == ("expired", "AUTH_INVALIDATED")
    assert [e["action"] for e in snapshot["events"]] == ["connect", "expire"]
    again = action(user, connection_id, "sync")
    assert (again.status_code, code(again)) == (409, "BROKER_ACTION_CONFLICT")
    # It can be disconnected, or authorized again.
    adapter.fail_portfolio = None
    state, params = state_and_params(start(user, connectionId=connection_id).json())
    assert (
        callback(user, state, params).json()["snapshot"]["connections"][0]["statusReason"] is None
    )


# ---------------------------------------------------------------- adapter errors


@pytest.mark.parametrize(
    ("failure", "status", "expected"),
    [
        (BrokerUnavailableError("down"), 503, "BROKER_UNAVAILABLE"),
        (BrokerMalformedResponseError("junk"), 502, "BROKER_MALFORMED_RESPONSE"),
        (BrokerRateLimitedError(17), 429, "BROKER_RATE_LIMITED"),
    ],
)
def test_adapter_failures_map_to_contract_errors(
    user: Browser,
    contract: Any,
    adapter: FlakyAdapter,
    failure: Exception,
    status: int,
    expected: str,
) -> None:
    connection_id = connect(user, contract)
    adapter.fail_portfolio = failure
    adapter.fail_exchange = failure
    synced = action(user, connection_id, "sync")
    assert (synced.status_code, code(synced)) == (status, expected)
    check(contract, "BrokerConnectionError", synced.json())
    assert "down" not in synced.text and "junk" not in synced.text  # no raw provider text
    state, params = state_and_params(start(user, connectionId=connection_id).json())
    exchanged = callback(user, state, params)
    assert (exchanged.status_code, code(exchanged)) == (status, expected)
    if status == 429:
        assert synced.headers["Retry-After"] == "17"
        assert synced.json()["retryAfterSeconds"] == 17
    # Nothing was recorded and the state is not spent by a transient failure.
    adapter.fail_exchange = None
    assert callback(user, state, params).status_code == 200
    assert [e["action"] for e in user.get(BASE).json()["events"]] == ["connect", "reconnect"]


# ----------------------------------------------------------------- disconnect


def test_disconnect_removes_the_connection_and_revokes(
    user: Browser, contract: Any, adapter: FlakyAdapter
) -> None:
    connection_id = connect(user, contract)
    done = action(user, connection_id, "disconnect")
    assert done.status_code == 200, done.text
    snapshot = done.json()
    check(contract, "BrokerConnectionsSnapshot", snapshot)
    assert snapshot["connections"] == []
    assert [(e["action"], e["connectionId"]) for e in snapshot["events"]] == [
        ("connect", connection_id),
        ("disconnect", connection_id),
    ]
    assert adapter.revoked == [("zerodha", "•••• 4821")]
    gone = action(user, connection_id, "disconnect")
    assert (gone.status_code, code(gone)) == (404, "BROKER_CONNECTION_NOT_FOUND")
    assert user.get(f"{BASE}/{connection_id}/portfolio").status_code == 404


def test_a_failed_revoke_never_blocks_the_disconnect(
    user: Browser, contract: Any, adapter: FlakyAdapter, clock: FakeClock
) -> None:
    connection_id = connect(user, contract)
    clock.advance(8 * 3600)  # expired connections can be disconnected too
    adapter.fail_revoke = True
    done = action(user, connection_id, "disconnect")
    assert done.status_code == 200, done.text
    assert done.json()["connections"] == []
    assert adapter.revoked  # it was tried


def test_disconnect_raises_an_alert_with_a_connection_link(user: Browser, contract: Any) -> None:
    connection_id = connect(user, contract)
    action(user, connection_id, "disconnect")
    rows = db_rows(
        db(), "SELECT kind, link_kind, link_id FROM alerts WHERE kind = 'BROKER_DISCONNECTED'"
    )
    assert [(r["kind"], r["link_kind"], r["link_id"]) for r in rows] == [
        ("BROKER_DISCONNECTED", "broker-connection", connection_id)
    ]


# ------------------------------------------------------------------- ownership


def test_another_users_connection_does_not_exist(
    client: TestClient, contract: Any, clock: FakeClock
) -> None:
    owner = Browser(client)
    owner.login_ready()
    other = Browser(client)
    other.login_ready(phone=OTHER_PHONE)
    open_step_up(clock)
    connection_id = connect(owner, contract)
    for response in (
        action(other, connection_id, "sync"),
        action(other, connection_id, "disconnect"),
        other.get(f"{BASE}/{connection_id}/portfolio"),
        start(other, connectionId=connection_id),
    ):
        assert (response.status_code, code(response)) == (404, "BROKER_CONNECTION_NOT_FOUND")
    assert other.get(BASE).json()["connections"] == []
    assert len(owner.get(BASE).json()["connections"]) == 1


def test_a_malformed_connection_id_is_a_bad_request(user: Browser) -> None:
    assert user.get(f"{BASE}/not-a-uuid/portfolio").status_code == 400
    assert action(user, "not-a-uuid", "sync").status_code == 400


def test_only_sync_and_disconnect_are_actions(user: Browser, contract: Any) -> None:
    connection_id = connect(user, contract)
    for name in ("connect", "reconnect", "place_order"):
        assert action(user, connection_id, name).status_code == 400


# ------------------------------------------------------ disabled and legacy


def test_disabled_provider_returns_503_everywhere(
    make_app: Callable[..., TestClient], clock: FakeClock
) -> None:
    browser = Browser(make_app(broker_provider="disabled"))
    browser.login_ready()
    open_step_up(clock)
    uid = "00000000-0000-4000-8000-000000000001"
    responses = [
        browser.get(BASE),
        browser.get(f"{BASE}/{uid}/portfolio"),
        start(browser, providerId="zerodha"),
        callback(browser, "s" * 20, {}),
        action(browser, uid, "sync"),
    ]
    for response in responses:
        assert (response.status_code, code(response)) == (503, "BROKER_UNAVAILABLE")


def test_the_deprecated_preview_shares_the_same_connections(user: Browser, contract: Any) -> None:
    assert user.post(f"{LEGACY}/zerodha/actions", json={"action": "connect"}).status_code == 200
    (conn,) = user.get(BASE).json()["connections"]
    assert (conn["providerId"], conn["status"]) == ("zerodha", "connected")
    legacy = user.get(LEGACY).json()["data"]
    assert [e["action"] for e in legacy["events"]] == ["connect"]
    assert set(legacy["connections"][0]["account"]["scopes"]) <= {
        "profile_read",
        "holdings_read",
        "orders_read",
    }
    # The provider is held, so a second connection through v2 is refused.
    assert code(start(user, providerId="zerodha")) == "BROKER_CONNECTION_LIMIT"
    # A v2 connection shows in the preview, and disconnecting through it works.
    other = connect(user, contract, "fyers")
    assert action(user, other, "sync").status_code == 200
    preview = user.get(LEGACY).json()["data"]
    assert [c["account"] is not None for c in preview["connections"]] == [True, True]
    assert user.post(f"{LEGACY}/fyers/actions", json={"action": "disconnect"}).status_code == 200
    assert [c["providerId"] for c in user.get(BASE).json()["connections"]] == ["zerodha"]


def test_preview_hides_expire_events_and_v2_shows_legacy_ones(
    user: Browser, contract: Any, clock: FakeClock, client: TestClient
) -> None:
    user.post(f"{LEGACY}/zerodha/actions", json={"action": "connect"})
    clock.advance(8 * 3600)
    worker(client)
    assert [e["action"] for e in user.get(LEGACY).json()["data"]["events"]] == ["connect"]
    assert [e["action"] for e in user.get(BASE).json()["events"]] == ["connect", "expire"]


# ------------------------------------------------------------------- migration


def test_migration_0014_round_trips_legacy_rows(db_url: str, user: Browser) -> None:
    user.post(f"{LEGACY}/zerodha/actions", json={"action": "connect"})
    before = db_rows(db_url, "SELECT id, masked_account_id FROM broker_connections")[0]
    command.downgrade(_alembic(db_url), "0013")
    legacy = db_rows(db_url, "SELECT provider, masked_account_id FROM broker_connections")
    assert [(r["provider"], r["masked_account_id"]) for r in legacy] == [
        ("zerodha", before["masked_account_id"])
    ]
    assert (
        db_rows(db_url, "SELECT 1 FROM pg_tables WHERE tablename = 'broker_authorizations'") == []
    )
    command.upgrade(_alembic(db_url), "head")
    row = db_rows(db_url, "SELECT account_ref, status_reason, portfolio FROM broker_connections")[0]
    assert row["account_ref"] == before["masked_account_id"]  # backfilled from the mask
    assert row["status_reason"] is None and row["portfolio"] is None
    event = db_rows(db_url, "SELECT connection_id FROM broker_events")[0]
    assert str(event["connection_id"]) == str(
        db_rows(db_url, "SELECT id FROM broker_connections")[0]["id"]
    )  # events were tied to the connection that existed


def test_masked_account_ids_fit_the_contract_pattern() -> None:
    for mask in ("•••• 4821", "•••• 0956"):
        assert re.fullmatch(r"•••• [A-Za-z0-9]{2,6}", mask)
