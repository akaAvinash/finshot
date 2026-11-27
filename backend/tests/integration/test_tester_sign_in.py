"""Invite-only tester sign-in: POST /api/v1/auth/login/tester, the operator
actions and the operation allowlist, over real PostgreSQL and Redis."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth import admin, tester
from app.auth.cookies import CSRF_COOKIE, SESSION_COOKIE
from app.auth.crypto import Keys
from app.auth.tester import TESTER_ALLOWED_OPERATIONS
from tests.integration.test_paper import _alembic
from tests.support import OTHER_PHONE, PHONE, Browser, FakeClock, db_rows, invite_phone

pytestmark = pytest.mark.integration

LOGIN = "/api/v1/auth/login/tester"
TESTER_PHONE = "+919000000001"
OTHER_TESTER = "+919000000002"
# Routes that run before sign-in or are the sign-in itself: they take no
# session, so the allowlist does not apply to them.
PRE_LOGIN_PATHS = {
    "/api/v1/auth/otp/request",
    "/api/v1/auth/otp/verify",
    "/api/v1/auth/login/totp",
    "/api/v1/auth/login/recovery",
    "/api/v1/auth/login/tester",
}
CONTRACT_DIR = Path(__file__).resolve().parents[3] / "contracts"


def db() -> str:
    return os.environ["TEST_DATABASE_URL"]


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    return make_app(tester_sign_in_enabled=True, paper_worker_enabled=False)


def operator(client: TestClient, work: Callable[[Any, Keys], Coroutine[Any, Any, Any]]) -> Any:
    keys: Keys = client.app.state.auth.keys  # type: ignore[attr-defined]

    async def run() -> Any:
        engine = create_async_engine(db())
        try:
            async with AsyncSession(engine) as session:
                return await work(session, keys)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def issue(
    client: TestClient, clock: FakeClock, phone: str = TESTER_PHONE, minutes: int = 15
) -> str:
    code: str = operator(
        client,
        lambda s, k: tester.issue_invite(s, k, phone, timedelta(minutes=minutes), clock.now),
    )
    return code


def redeem(browser: Browser, phone: str, code: str) -> Any:
    if browser.csrf is None:
        browser.get_csrf()
    response = browser.post(LOGIN, json={"phone": phone, "inviteCode": code})
    if response.status_code == 200:
        browser.csrf = response.json()["csrfToken"]
    return response


@pytest.fixture
def signed_in(client: TestClient, clock: FakeClock) -> Browser:
    browser = Browser(client)
    assert redeem(browser, TESTER_PHONE, issue(client, clock)).status_code == 200
    return browser


def code_of(response: Any) -> str:
    return str(response.json()["code"])


# ------------------------------------------------------------------- disabled


def test_disabled_by_default_is_not_found(make_app: Callable[..., TestClient]) -> None:
    browser = Browser(make_app())
    response = browser.post(LOGIN, json={"phone": TESTER_PHONE, "inviteCode": "A" * 22})
    assert (response.status_code, code_of(response)) == (404, "NOT_FOUND")
    assert response.json()["requestId"]


def test_disabling_ends_every_tester_session(
    make_app: Callable[..., TestClient], client: TestClient, clock: FakeClock
) -> None:
    browser = Browser(client)
    assert redeem(browser, TESTER_PHONE, issue(client, clock)).status_code == 200
    assert browser.get("/api/v1/auth/me").status_code == 200
    off = Browser(make_app(tester_sign_in_enabled=False))
    off.jar = browser.jar
    assert off.get("/api/v1/auth/me").status_code == 401
    rows = db_rows(db(), "SELECT revoked_at FROM sessions WHERE tester_invite_id IS NOT NULL")
    assert rows and all(r["revoked_at"] is not None for r in rows)


# --------------------------------------------------------------------- redeem


def test_redeem_gives_a_tester_session(client: TestClient, clock: FakeClock) -> None:
    browser = Browser(client)
    response = redeem(browser, TESTER_PHONE, issue(client, clock))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["totpEnabled"] is False
    assert body["session"]["access"] == "tester"
    assert body["session"]["stepUpUntil"] is None
    assert len(body["csrfToken"]) >= 32
    assert response.headers["Cache-Control"] == "no-store"
    cookies = [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]
    assert len(cookies) == 2
    assert cookies[0].startswith(SESSION_COOKIE) and cookies[1].startswith(CSRF_COOKIE)
    # Expires within two hours; idle can never run past that.
    expires = clock.now + timedelta(hours=2)
    assert body["session"]["expiresAt"].startswith(expires.strftime("%Y-%m-%dT%H:%M:%S"))
    assert body["session"]["idleExpiresAt"] <= body["session"]["expiresAt"]
    me = browser.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["session"]["access"] == "tester"
    assert me.json()["user"]["totpEnabled"] is False


def test_regular_sessions_do_not_report_an_access_field(client: TestClient) -> None:
    browser = Browser(client)
    browser.login_ready()
    session = browser.get("/api/v1/auth/me").json()["session"]
    assert "access" not in session


def test_a_code_works_once(client: TestClient, clock: FakeClock) -> None:
    code = issue(client, clock)
    assert redeem(Browser(client), TESTER_PHONE, code).status_code == 200
    again = redeem(Browser(client), TESTER_PHONE, code)
    assert (again.status_code, code_of(again)) == (401, "INVALID_CREDENTIALS")


def test_every_failure_looks_the_same(client: TestClient, clock: FakeClock) -> None:
    code = issue(client, clock)
    issue(client, clock, OTHER_TESTER)
    shapes = set()
    for phone, attempt in (
        (TESTER_PHONE, "B" * 22),  # wrong code
        (OTHER_TESTER, code),  # another tester's code
        ("+919000000009", code),  # unknown number
        (PHONE, code),  # not a tester
    ):
        response = redeem(Browser(client), phone, attempt)
        assert response.status_code == 401
        body = response.json()
        body.pop("requestId")
        shapes.add(json.dumps(body, sort_keys=True))
    assert len(shapes) == 1


def test_a_code_expires_within_15_minutes(client: TestClient, clock: FakeClock) -> None:
    code = issue(client, clock)
    clock.advance(15 * 60)  # at the expiry instant
    late = redeem(Browser(client), TESTER_PHONE, code)
    assert (late.status_code, code_of(late)) == (401, "INVALID_CREDENTIALS")
    assert db_rows(db(), "SELECT 1 FROM sessions WHERE tester_invite_id IS NOT NULL") == []
    # Still fine one second before.
    fresh = issue(client, clock)
    clock.advance(15 * 60 - 1)
    assert redeem(Browser(client), TESTER_PHONE, fresh).status_code == 200


def test_issuing_again_replaces_the_unused_code(client: TestClient, clock: FakeClock) -> None:
    first = issue(client, clock)
    second = issue(client, clock)
    assert redeem(Browser(client), TESTER_PHONE, first).status_code == 401
    assert redeem(Browser(client), TESTER_PHONE, second).status_code == 200


def test_concurrent_replay_has_one_winner(client: TestClient, clock: FakeClock) -> None:
    code = issue(client, clock)
    browser = Browser(client)
    browser.get_csrf()
    active = browser.activate()
    headers = {
        **browser.headers(),
        "Cookie": "; ".join(f"{c.name}={c.value}" for c in browser.jar.jar),
    }
    active.cookies.clear()

    def attempt(_: int) -> int:
        response = active.post(
            LOGIN, json={"phone": TESTER_PHONE, "inviteCode": code}, headers=headers
        )
        return int(response.status_code)

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(attempt, range(4)))
    assert statuses.count(200) == 1
    assert statuses.count(401) == 3
    assert len(db_rows(db(), "SELECT 1 FROM sessions WHERE tester_invite_id IS NOT NULL")) == 1


def test_redeem_needs_a_pre_login_csrf_token(client: TestClient, clock: FakeClock) -> None:
    code = issue(client, clock)
    browser = Browser(client)
    browser.get_csrf()
    wrong = browser.send(
        "POST",
        LOGIN,
        json={"phone": TESTER_PHONE, "inviteCode": code},
        headers=browser.headers(csrf="nope"),
    )
    assert (wrong.status_code, code_of(wrong)) == (403, "CSRF_FAILED")
    assert redeem(browser, TESTER_PHONE, code).status_code == 200  # the code was not spent


def test_bad_bodies_are_400(client: TestClient) -> None:
    browser = Browser(client)
    browser.get_csrf()
    for body in (
        {"phone": TESTER_PHONE},
        {"phone": TESTER_PHONE, "inviteCode": "short"},
        {"phone": "12345", "inviteCode": "A" * 22},
        {"phone": TESTER_PHONE, "inviteCode": "A" * 22, "extra": 1},
    ):
        assert browser.post(LOGIN, json=body).status_code == 400


def test_failures_are_throttled_per_number_even_when_unknown(client: TestClient) -> None:
    for phone in (TESTER_PHONE, "+919000000009"):
        browser = Browser(client)
        statuses = [redeem(browser, phone, "C" * 22).status_code for _ in range(7)]
        assert statuses[:5] == [401] * 5
        assert 429 in statuses[5:]


def test_the_session_ends_after_two_hours(
    make_app: Callable[..., TestClient], clock: FakeClock
) -> None:
    # An idle window longer than the session, so only the two hours can end it.
    client = make_app(tester_sign_in_enabled=True, session_idle_ttl_seconds=86_400)
    browser = Browser(client)
    assert redeem(browser, TESTER_PHONE, issue(client, clock)).status_code == 200
    clock.advance(2 * 3600 - 60)
    assert browser.get("/api/v1/auth/me").status_code == 200
    clock.advance(60)
    assert browser.get("/api/v1/auth/me").status_code == 401


# --------------------------------------------------------- revoke and purge


def test_revoking_ends_the_session_and_unused_codes(client: TestClient, clock: FakeClock) -> None:
    live = Browser(client)
    assert redeem(live, TESTER_PHONE, issue(client, clock)).status_code == 200
    unused = issue(client, clock)
    assert operator(client, lambda s, k: tester.revoke_access(s, TESTER_PHONE, clock.now)) is True
    assert live.get("/api/v1/auth/me").status_code == 401  # at once
    revoked = redeem(Browser(client), TESTER_PHONE, unused)
    assert (revoked.status_code, code_of(revoked)) == (401, "INVALID_CREDENTIALS")
    # The owner can issue again afterwards.
    assert redeem(Browser(client), TESTER_PHONE, issue(client, clock)).status_code == 200


def test_revoking_one_tester_leaves_another(client: TestClient, clock: FakeClock) -> None:
    a, b = Browser(client), Browser(client)
    assert redeem(a, TESTER_PHONE, issue(client, clock)).status_code == 200
    assert redeem(b, OTHER_TESTER, issue(client, clock, OTHER_TESTER)).status_code == 200
    operator(client, lambda s, k: tester.revoke_access(s, TESTER_PHONE, clock.now))
    assert a.get("/api/v1/auth/me").status_code == 401
    assert b.get("/api/v1/auth/me").status_code == 200


def test_purge_removes_credentials_but_keeps_audit(client: TestClient, clock: FakeClock) -> None:
    browser = Browser(client)
    assert redeem(browser, TESTER_PHONE, issue(client, clock)).status_code == 200
    assert operator(client, lambda s, k: tester.purge_credentials(s, TESTER_PHONE, clock.now))
    assert browser.get("/api/v1/auth/me").status_code == 401
    assert db_rows(db(), "SELECT 1 FROM tester_invites") == []
    assert db_rows(db(), "SELECT purged_at FROM tester_identities")[0]["purged_at"] is not None
    actions = {r["action"] for r in db_rows(db(), "SELECT action FROM audit_events")}
    assert {"tester.invite_issued", "tester.redeemed", "tester.credentials_purged"} <= actions
    # A purged identity cannot sign in again until the owner issues a new code.
    assert (
        operator(client, lambda s, k: tester.revoke_access(s, "+919000000009", clock.now)) is False
    )


def test_audit_never_holds_codes_phones_or_tokens(client: TestClient, clock: FakeClock) -> None:
    code = issue(client, clock)
    browser = Browser(client)
    response = redeem(browser, TESTER_PHONE, code)
    redeem(Browser(client), TESTER_PHONE, "D" * 22)
    operator(client, lambda s, k: tester.revoke_access(s, TESTER_PHONE, clock.now))
    dump = json.dumps(db_rows(db(), "SELECT action, resource, metadata_redacted FROM audit_events"))
    digit_tail = TESTER_PHONE[-10:]
    for secret in (code, TESTER_PHONE, digit_tail, response.json()["csrfToken"]):
        assert secret not in dump
    assert "D" * 22 not in dump
    assert code not in json.dumps(db_rows(db(), "SELECT code_digest FROM tester_invites"))


# --------------------------------------------- identity separation from regular


def test_regular_sign_in_cannot_reach_a_tester(client: TestClient, clock: FakeClock) -> None:
    code = issue(client, clock)
    browser = Browser(client)
    browser.get_csrf()
    asked = browser.request_otp(TESTER_PHONE, invite=False)
    assert asked.status_code in (202, 400, 401, 403)
    if asked.status_code == 202:
        assert browser.verify(asked.json()["challengeId"], "123456").status_code == 401
    for path, body in (
        ("/api/v1/auth/login/totp", {"phone": TESTER_PHONE, "code": "123456"}),
        ("/api/v1/auth/login/recovery", {"phone": TESTER_PHONE, "recoveryCode": "ABCDE-FGHIJ"}),
    ):
        assert browser.post(path, json=body).status_code == 401
    assert redeem(Browser(client), TESTER_PHONE, code).status_code == 200  # code unaffected


def test_operator_refuses_regular_numbers_and_long_codes(
    client: TestClient, clock: FakeClock
) -> None:
    Browser(client).login_ready()  # a regular account with an invite
    invite_phone(OTHER_PHONE)  # an invited number that has not signed in yet
    for phone in (PHONE, OTHER_PHONE):
        with pytest.raises(tester.TesterError):
            issue(client, clock, phone)
    with pytest.raises(tester.TesterError):
        issue(client, clock, minutes=16)
    issue(client, clock)
    with pytest.raises(admin.AdminError):
        operator(client, lambda s, k: admin.add_invite(s, TESTER_PHONE, None, clock.now))


def test_database_caps_invites_at_15_minutes(client: TestClient, clock: FakeClock) -> None:
    issue(client, clock)
    with pytest.raises(Exception, match="expiry_within_15_minutes"):
        db_rows(db(), "UPDATE tester_invites SET expires_at = created_at + interval '16 minutes'")


# --------------------------------------------------------- the allowlist


def test_allowlist_matches_the_contract_proposal() -> None:
    proposal = yaml.safe_load((CONTRACT_DIR / "tester-sign-in.openapi.yaml").read_text())
    assert set(proposal["x-tester-allowed-operations"]) == TESTER_ALLOWED_OPERATIONS
    assert len(TESTER_ALLOWED_OPERATIONS) == 26


def _served(client: TestClient) -> list[tuple[str, str, str]]:
    """(method, path, operationId) of every served API operation."""
    paths = client.get("/openapi.json").json()["paths"]
    return [
        (method.upper(), path, op["operationId"])
        for path, ops in paths.items()
        if path.startswith("/api/v1/")
        for method, op in ops.items()
    ]


def test_every_allowed_operation_exists(client: TestClient) -> None:
    assert TESTER_ALLOWED_OPERATIONS <= {op for _, _, op in _served(client)}


def test_tester_sessions_are_refused_on_every_other_route(
    client: TestClient, signed_in: Browser
) -> None:
    """Sweeps every served operation: one outside the allowlist (including any
    without an explicit operation id, or added later) is 403
    TESTER_ACCESS_DENIED, before CSRF and before the body is read."""
    denied = 0
    for method, path, operation_id in _served(client):
        if path in PRE_LOGIN_PATHS or operation_id == "logout":
            continue  # logout ends the shared session; test_tester_logout_works covers it
        response = signed_in.send(
            method,
            _fill(path),
            json={} if method != "GET" else None,
            headers=signed_in.headers(),
        )
        blocked = (
            response.status_code == 403 and response.json().get("code") == "TESTER_ACCESS_DENIED"
        )
        if operation_id in TESTER_ALLOWED_OPERATIONS:
            assert not blocked, (method, path)
        else:
            assert blocked, (method, path, operation_id, response.status_code)
            denied += 1
    assert denied >= 15  # the sweep covered the account, step-up, broker and settings routes


def _fill(path: str) -> str:
    out = path
    while "{" in out:
        start = out.index("{")
        end = out.index("}", start)
        out = out[:start] + str(uuid.uuid4()) + out[end + 1 :]
    return out


def test_tester_never_gets_step_up(signed_in: Browser) -> None:
    denied = signed_in.post("/api/v1/auth/step-up", json={"code": "123456"})
    assert (denied.status_code, code_of(denied)) == (403, "TESTER_ACCESS_DENIED")
    assert signed_in.get("/api/v1/auth/me").json()["session"]["stepUpUntil"] is None
    for method, path in (
        ("PUT", "/api/v1/settings/trade-controls"),
        ("POST", "/api/v1/broker-connections/authorizations"),
        ("POST", "/api/v1/brokers/preview/zerodha/actions"),
        ("PUT", "/api/v1/settings/profile"),
        ("GET", "/api/v1/auth/sessions"),
    ):
        response = signed_in.send(method, path, json={}, headers=signed_in.headers())
        assert (response.status_code, code_of(response)) == (403, "TESTER_ACCESS_DENIED"), path


def test_a_tester_can_use_demo_and_paper_workspaces(signed_in: Browser) -> None:
    for path in (
        "/api/v1/market/instruments",
        "/api/v1/strategies/preview",
        "/api/v1/backtests/preview",
        "/api/v1/auto-trading/paper",
        "/api/v1/reports/paper",
        "/api/v1/agents",
        "/api/v1/alerts",
        "/api/v1/alerts/preferences",
        "/api/v1/settings/trade-controls",
        "/api/v1/broker-connections",
    ):
        response = signed_in.get(path)
        assert response.status_code == 200, (path, response.text[:200])
    snapshot = signed_in.get("/api/v1/broker-connections").json()
    assert snapshot["environment"] == "DEMO" and snapshot["connections"] == []


def test_tester_and_regular_data_are_separate(client: TestClient, signed_in: Browser) -> None:
    regular = Browser(client)
    regular.login_ready()
    assert (
        signed_in.get("/api/v1/auth/me").json()["user"]["id"]
        != (regular.get("/api/v1/auth/me").json()["user"]["id"])
    )
    assert signed_in.get("/api/v1/strategies/preview").json()["data"]["strategies"] == []


def test_tester_logout_works(signed_in: Browser) -> None:
    assert signed_in.post("/api/v1/auth/logout").status_code == 204
    assert signed_in.get("/api/v1/auth/me").status_code == 401


# ------------------------------------------------------------------- migration


def test_migration_0015_round_trips(
    db_url: str, client: TestClient, clock: FakeClock, signed_in: Browser
) -> None:
    command.downgrade(_alembic(db_url), "0014")
    assert db_rows(db_url, "SELECT 1 FROM pg_tables WHERE tablename = 'tester_invites'") == []
    assert db_rows(db_url, "SELECT 1 FROM sessions") == []  # the tester session went with it
    assert db_rows(db_url, "SELECT 1 FROM users WHERE phone_e164 = :p", p=TESTER_PHONE) == []
    command.upgrade(_alembic(db_url), "head")
    assert db_rows(db_url, "SELECT 1 FROM pg_tables WHERE tablename = 'tester_invites'")


def test_issuing_again_after_a_purge_works(client: TestClient, clock: FakeClock) -> None:
    redeem(Browser(client), TESTER_PHONE, issue(client, clock))
    assert operator(client, lambda s, k: tester.purge_credentials(s, TESTER_PHONE, clock.now))
    fresh = redeem(Browser(client), TESTER_PHONE, issue(client, clock))
    assert fresh.status_code == 200, fresh.text
    assert db_rows(db(), "SELECT purged_at FROM tester_identities")[0]["purged_at"] is None
    # Regular-account numbers are still refused.
    Browser(client).login_ready()
    with pytest.raises(tester.TesterError):
        issue(client, clock, PHONE)


def test_concurrent_issuance_leaves_one_live_code(client: TestClient, clock: FakeClock) -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(lambda _: issue(client, clock), range(4)))
    assert len(set(codes)) == 4
    live = db_rows(
        db(), "SELECT 1 FROM tester_invites WHERE used_at IS NULL AND revoked_at IS NULL"
    )
    assert len(live) == 1


def test_redemption_overlapping_revocation_never_leaves_a_live_session(
    client: TestClient, clock: FakeClock
) -> None:
    """Holds the invite row so a redemption and a revocation for the same
    tester are both waiting on it, then releases them together."""

    def hold_row(started: threading.Event, release: threading.Event) -> None:
        async def run() -> None:
            engine = create_async_engine(db())
            try:
                async with engine.begin() as conn:
                    await conn.execute(text("SELECT 1 FROM tester_invites FOR UPDATE"))
                    started.set()
                    await asyncio.to_thread(release.wait, 10)
            finally:
                await engine.dispose()

        asyncio.run(run())

    for _ in range(4):
        code = issue(client, clock)
        browser = Browser(client)
        browser.get_csrf()
        active = browser.activate()
        headers = {
            **browser.headers(),
            "Cookie": "; ".join(f"{c.name}={c.value}" for c in browser.jar.jar),
        }
        active.cookies.clear()
        started, release = threading.Event(), threading.Event()
        holder = threading.Thread(target=hold_row, args=(started, release))
        holder.start()
        assert started.wait(10)
        with ThreadPoolExecutor(max_workers=2) as pool:
            redeeming = pool.submit(
                active.post,
                LOGIN,
                json={"phone": TESTER_PHONE, "inviteCode": code},
                headers=headers,
            )
            revoking = pool.submit(
                lambda: operator(
                    client, lambda s, k: tester.revoke_access(s, TESTER_PHONE, clock.now)
                )
            )
            time.sleep(0.5)  # both are now waiting on the held row
            release.set()
            assert redeeming.result(20).status_code in (200, 401)
            assert revoking.result(20) is True
        holder.join(10)
        live = db_rows(
            db(), "SELECT 1 FROM sessions WHERE tester_invite_id IS NOT NULL AND revoked_at IS NULL"
        )
        assert live == []
    assert redeem(Browser(client), TESTER_PHONE, issue(client, clock)).status_code == 200


def test_a_failed_startup_cleanup_is_retried(
    make_app: Callable[..., TestClient],
    client: TestClient,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = Browser(client)
    assert redeem(browser, TESTER_PHONE, issue(client, clock)).status_code == 200
    real = tester.revoke_all_tester_sessions
    calls = {"n": 0}

    async def flaky(db: AsyncSession, now: Any) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("database down")
        return int(await real(db, now))

    monkeypatch.setattr(tester, "revoke_all_tester_sessions", flaky)
    make_app(tester_sign_in_enabled=False)  # starts disabled; the first cleanup fails
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        rows = db_rows(db(), "SELECT revoked_at FROM sessions WHERE tester_invite_id IS NOT NULL")
        if rows and all(r["revoked_at"] is not None for r in rows):
            break
        time.sleep(0.2)
    assert calls["n"] >= 2
    # Re-enabled: the earlier session stays dead.
    assert browser.get("/api/v1/auth/me").status_code == 401


def test_concurrent_issue_and_purge_do_not_deadlock(client: TestClient, clock: FakeClock) -> None:
    for _ in range(5):
        issue(client, clock)  # leaves an unused invite for both operations to touch
        with ThreadPoolExecutor(max_workers=2) as pool:
            issuing = pool.submit(issue, client, clock)
            purging = pool.submit(
                operator, client, lambda s, k: tester.purge_credentials(s, TESTER_PHONE, clock.now)
            )
            assert purging.result(30) is True
            assert issuing.result(30)
        live = db_rows(
            db(), "SELECT 1 FROM tester_invites WHERE used_at IS NULL AND revoked_at IS NULL"
        )
        assert len(live) <= 1
