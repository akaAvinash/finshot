"""Phone number change: /api/v1/settings/phone/change over real Postgres and Redis."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import asyncpg
import pytest
import yaml  # type: ignore[import-untyped]
from alembic import command
from fastapi.testclient import TestClient

from tests.integration.test_paper import CONTRACT_PATH, _alembic, check
from tests.support import (
    OTHER_PHONE,
    PHONE,
    Browser,
    FakeClock,
    FixedOtpProvider,
    db_rows,
    invite_phone,
)

pytestmark = pytest.mark.integration

REQUEST = "/api/v1/settings/phone/change"
CONFIRM = f"{REQUEST}/confirm"
NEW_PHONE = "+917654321098"


def db() -> str:
    return os.environ["TEST_DATABASE_URL"]


@pytest.fixture
def contract() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    return make_app(paper_worker_enabled=False, backtest_worker_enabled=False)


def open_step_up(clock: FakeClock) -> None:
    db_rows(db(), "UPDATE sessions SET step_up_until = :t", t=clock.now + timedelta(hours=1))


@pytest.fixture
def user(client: TestClient, clock: FakeClock) -> Browser:
    browser = Browser(client)
    browser.login_ready()
    open_step_up(clock)
    return browser


def ask(browser: Browser, phone: str = NEW_PHONE, **kw: Any) -> Any:
    return browser.post(REQUEST, json={"newPhone": phone}, **kw)


def confirm(browser: Browser, challenge_id: str, code: str = "123456", **kw: Any) -> Any:
    return browser.post(CONFIRM, json={"challengeId": challenge_id, "code": code}, **kw)


def code_of(response: Any) -> str:
    return str(response.json()["code"])


def test_change_moves_the_account_invite_and_sessions(
    client: TestClient,
    user: Browser,
    clock: FakeClock,
    provider: FixedOtpProvider,
    contract: dict[str, Any],
) -> None:
    other = Browser(client)
    other.login_ready()  # a second session of the same account
    open_step_up(clock)
    provider.deliveries.clear()

    asked = ask(user)
    assert asked.status_code == 202, asked.text
    check(contract, "PhoneChangeChallenge", asked.json())
    assert asked.json()["destinationMasked"] == "+91******1098"
    assert provider.deliveries == [(NEW_PHONE, "123456")]

    done = confirm(user, asked.json()["challengeId"])
    assert done.status_code == 200, done.text
    check(contract, "SettingsProfile", done.json())
    assert done.json()["phoneMasked"] == "+91******1098"

    assert db_rows(db(), "SELECT phone_e164 FROM users") == [{"phone_e164": NEW_PHONE}]
    invites = {
        r["phone_e164"]: r["revoked_at"]
        for r in db_rows(db(), "SELECT phone_e164, revoked_at FROM invites")
    }
    assert invites[NEW_PHONE] is None and invites[PHONE] is not None
    # The caller's session continues; the other one has ended.
    assert user.get("/api/v1/auth/me").status_code == 200
    assert user.get("/api/v1/settings/profile").json()["phoneMasked"] == "+91******1098"
    assert other.get("/api/v1/auth/me").status_code == 401

    alerts = user.get("/api/v1/alerts").json()["items"]
    assert alerts[0]["kind"] == "PHONE_CHANGED" and alerts[0]["severity"] == "critical"
    check(contract, "Alert", alerts[0])

    audit = db_rows(db(), "SELECT action, metadata_redacted, resource FROM audit_events")
    actions = [r["action"] for r in audit]
    assert "phone.change_requested" in actions and "phone.changed" in actions
    dump = json.dumps(audit, default=str)
    for secret in (PHONE[3:], NEW_PHONE[3:], "123456"):
        assert secret not in dump


def test_the_old_number_can_no_longer_sign_in(user: Browser, client: TestClient) -> None:
    confirm(user, ask(user).json()["challengeId"])
    stranger = Browser(client)
    stranger.get_csrf()
    challenge = stranger.request_otp(PHONE, invite=False)
    assert challenge.status_code == 202
    assert stranger.verify(challenge.json()["challengeId"], "123456").status_code == 401


def test_step_up_is_required_for_both_steps(user: Browser, clock: FakeClock) -> None:
    asked = ask(user)
    db_rows(db(), "UPDATE sessions SET step_up_until = NULL")
    assert (ask(user).status_code, code_of(ask(user))) == (403, "STEP_UP_REQUIRED")
    refused = confirm(user, asked.json()["challengeId"])
    assert (refused.status_code, code_of(refused)) == (403, "STEP_UP_REQUIRED")
    assert db_rows(db(), "SELECT phone_e164 FROM users") == [{"phone_e164": PHONE}]


def test_csrf_is_checked_before_step_up(client: TestClient) -> None:
    browser = Browser(client)
    browser.login_ready()
    response = ask(browser, headers=browser.headers(csrf="wrong"))
    assert (response.status_code, code_of(response)) == (403, "CSRF_FAILED")


def test_setup_is_required_first(client: TestClient) -> None:
    browser = Browser(client)
    browser.login()
    response = ask(browser)
    assert (response.status_code, code_of(response)) == (403, "TOTP_SETUP_REQUIRED")


def test_own_number_is_refused_openly(user: Browser) -> None:
    response = ask(user, PHONE)
    assert (response.status_code, code_of(response)) == (400, "PHONE_UNCHANGED")


@pytest.mark.parametrize("phone", ["9876543210", "+915876543210", "+91987654321"])
def test_bad_numbers_are_invalid(user: Browser, phone: str) -> None:
    response = ask(user, phone)
    assert (response.status_code, code_of(response)) == (400, "INVALID_REQUEST")


@pytest.mark.parametrize("kind", ["account", "invite", "revoked-invite"])
def test_a_taken_number_looks_the_same_and_can_never_be_confirmed(
    client: TestClient, user: Browser, provider: FixedOtpProvider, kind: str
) -> None:
    if kind == "account":
        Browser(client).login_ready(phone=OTHER_PHONE)
        open_step_up(FakeClock())
    else:
        invite_phone(OTHER_PHONE)
        if kind == "revoked-invite":
            db_rows(
                db(), "UPDATE invites SET revoked_at = now() WHERE phone_e164 = :p", p=OTHER_PHONE
            )
    provider.deliveries.clear()
    free = ask(user, "+916543210987")
    taken = ask(user, OTHER_PHONE)
    assert taken.status_code == free.status_code == 202
    assert set(taken.json()) == set(free.json())
    assert [d[0] for d in provider.deliveries] == ["+916543210987"]
    refused = confirm(user, taken.json()["challengeId"])
    assert (refused.status_code, code_of(refused)) == (400, "PHONE_CHANGE_CODE_INVALID")
    assert db_rows(db(), "SELECT 1 FROM users WHERE phone_e164 = :p", p=PHONE)


@pytest.mark.parametrize("kind", ["account", "invite"])
def test_a_number_taken_after_the_request_cannot_be_confirmed(
    client: TestClient, user: Browser, kind: str
) -> None:
    challenge = ask(user, "+916543210987").json()["challengeId"]
    if kind == "account":
        Browser(client).login_ready(phone="+916543210987")
        open_step_up(FakeClock())
    else:
        invite_phone("+916543210987")
    before_invites = db_rows(db(), "SELECT phone_e164, revoked_at FROM invites ORDER BY 1")
    refused = confirm(user, challenge)
    assert (refused.status_code, code_of(refused)) == (400, "PHONE_CHANGE_CODE_INVALID")
    assert db_rows(db(), "SELECT 1 FROM users WHERE phone_e164 = :p", p=PHONE)
    assert db_rows(db(), "SELECT phone_e164, revoked_at FROM invites ORDER BY 1") == before_invites
    assert db_rows(db(), "SELECT 1 FROM sessions WHERE revoked_at IS NOT NULL") == []
    assert user.get("/api/v1/auth/me").status_code == 200


def after_the_first_clock_read(
    client: TestClient, clock: FakeClock, act: Callable[[], None]
) -> None:
    """Make `confirm` see the world change between its attempt count and the
    transaction that changes the number, as a wait for the number's lock would.
    Only reads made by `PhoneChangeService.confirm` itself are counted."""
    auth = client.app.state.auth  # type: ignore[attr-defined]
    reads = {"n": 0}

    def ticking() -> Any:
        caller = sys._getframe(1)
        if caller.f_code.co_name == "confirm" and caller.f_code.co_filename.endswith(
            "phone_change.py"
        ):
            reads["n"] += 1
            if reads["n"] == 2:
                worker = threading.Thread(target=act)  # db_rows cannot run on the loop
                worker.start()
                worker.join()
        return clock.now

    auth.clock = ticking


@pytest.mark.parametrize("what", ["expired", "revoked", "step-up-closed"])
def test_expiry_and_session_are_rechecked_when_the_number_changes(
    client: TestClient, user: Browser, clock: FakeClock, what: str
) -> None:
    challenge = ask(user).json()["challengeId"]
    acts = {
        "expired": lambda: db_rows(
            db(), "UPDATE phone_change_challenges SET expires_at = :t", t=clock.now
        ),
        "revoked": lambda: db_rows(db(), "UPDATE sessions SET revoked_at = :t", t=clock.now),
        "step-up-closed": lambda: db_rows(
            db(), "UPDATE sessions SET step_up_until = :t", t=clock.now
        ),
    }
    after_the_first_clock_read(client, clock, acts[what])
    refused = confirm(user, challenge)
    assert code_of(refused) == "PHONE_CHANGE_CODE_INVALID"
    assert db_rows(db(), "SELECT phone_e164 FROM users") == [{"phone_e164": PHONE}]
    assert db_rows(db(), "SELECT 1 FROM alerts WHERE kind = 'PHONE_CHANGED'") == []


def confirm_while_another_connection_holds(
    user: Browser,
    challenge: str,
    lock_sql: str,
    while_blocked: Callable[[], None],
    finish_sql: str | None = None,
) -> Any:
    """Hold `lock_sql` on another connection, start a confirmation, wait until it is
    really blocked on a lock, run `while_blocked`, then let the holder (optionally
    running `finish_sql` first) commit. Returns the confirmation's response."""
    locked, release = threading.Event(), threading.Event()

    def holder() -> None:
        async def hold() -> None:
            conn = await asyncpg.connect(db().replace("+asyncpg", ""))
            try:
                async with conn.transaction():
                    await conn.execute(lock_sql)
                    locked.set()
                    await asyncio.get_running_loop().run_in_executor(None, release.wait, 30)
                    if finish_sql:
                        await conn.execute(finish_sql)
            finally:
                await conn.close()

        asyncio.run(hold())

    thread = threading.Thread(target=holder)
    thread.start()
    result: list[Any] = []
    caller = threading.Thread(target=lambda: result.append(confirm(user, challenge)))
    try:
        assert locked.wait(10)
        caller.start()
        for _ in range(100):  # bounded: ten seconds
            waiting = db_rows(
                db(),
                "SELECT count(*) AS n FROM pg_stat_activity"
                " WHERE wait_event_type = 'Lock' AND datname = current_database()",
            )[0]["n"]
            if waiting:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("the confirmation never blocked on the lock")
        while_blocked()
    finally:
        release.set()
        if caller.is_alive():
            caller.join(20)
        thread.join(10)
    return result[0]


def test_step_up_is_judged_after_waiting_for_the_account_lock(
    user: Browser, clock: FakeClock
) -> None:
    """A confirmation that waits for the account row while the step-up window closes
    must be refused: `now` is sampled after the wait, not before it."""
    challenge = ask(user).json()["challengeId"]
    db_rows(
        db(), "UPDATE phone_change_challenges SET expires_at = :t", t=clock.now + timedelta(days=2)
    )
    refused = confirm_while_another_connection_holds(
        user, challenge, "SELECT 1 FROM users FOR UPDATE", lambda: clock.advance(3601)
    )
    assert code_of(refused) == "PHONE_CHANGE_CODE_INVALID"
    assert db_rows(db(), "SELECT phone_e164 FROM users") == [{"phone_e164": PHONE}]


def test_a_logout_in_flight_ends_the_confirmation(user: Browser) -> None:
    """The initiating session is locked while it is checked: a logout that is already
    revoking it must finish first, and the confirmation must then see it revoked."""
    challenge = ask(user).json()["challengeId"]
    refused = confirm_while_another_connection_holds(
        user,
        challenge,
        "SELECT 1 FROM sessions FOR UPDATE",
        lambda: None,
        "UPDATE sessions SET revoked_at = now()",
    )
    assert code_of(refused) == "PHONE_CHANGE_CODE_INVALID"
    assert db_rows(db(), "SELECT phone_e164 FROM users") == [{"phone_e164": PHONE}]
    assert db_rows(db(), "SELECT 1 FROM alerts WHERE kind = 'PHONE_CHANGED'") == []


def test_wrong_codes_exhaust_the_challenge(user: Browser) -> None:
    challenge = ask(user).json()["challengeId"]
    for _ in range(5):
        assert code_of(confirm(user, challenge, "000000")) == "PHONE_CHANGE_CODE_INVALID"
    assert confirm(user, challenge).status_code == 400
    assert db_rows(db(), "SELECT phone_e164 FROM users") == [{"phone_e164": PHONE}]


def test_a_challenge_works_once(user: Browser) -> None:
    challenge = ask(user).json()["challengeId"]
    assert confirm(user, challenge).status_code == 200
    assert code_of(confirm(user, challenge)) == "PHONE_CHANGE_CODE_INVALID"


def test_a_challenge_expires(user: Browser, clock: FakeClock) -> None:
    challenge = ask(user).json()["challengeId"]
    clock.advance(301)
    open_step_up(clock)
    assert code_of(confirm(user, challenge)) == "PHONE_CHANGE_CODE_INVALID"


def test_another_session_cannot_confirm(
    client: TestClient, user: Browser, clock: FakeClock
) -> None:
    challenge = ask(user).json()["challengeId"]
    second = Browser(client)
    deactivated = db_rows(db(), "DELETE FROM totp_credentials RETURNING user_id")
    assert deactivated
    second.login()
    db_rows(
        db(),
        "INSERT INTO totp_credentials (user_id, secret_enc, created_at, confirmed_at, last_step)"
        " SELECT id, :s, now(), now(), 0 FROM users",
        s=b"x",
    )
    open_step_up(clock)
    assert code_of(confirm(second, challenge)) == "PHONE_CHANGE_CODE_INVALID"


def test_another_account_cannot_confirm(
    client: TestClient, user: Browser, clock: FakeClock
) -> None:
    challenge = ask(user).json()["challengeId"]
    other = Browser(client)
    other.login_ready(phone=OTHER_PHONE)
    open_step_up(clock)
    assert code_of(confirm(other, challenge)) == "PHONE_CHANGE_CODE_INVALID"


def test_a_phone_change_challenge_cannot_sign_in(client: TestClient, user: Browser) -> None:
    challenge = ask(user).json()["challengeId"]
    stranger = Browser(client)
    stranger.get_csrf()
    assert stranger.verify(challenge, "123456").status_code == 401


def test_a_sign_in_challenge_cannot_confirm(client: TestClient, user: Browser) -> None:
    other = Browser(client)
    other.get_csrf()
    sign_in = other.request_otp(NEW_PHONE).json()["challengeId"]
    assert code_of(confirm(user, sign_in)) == "PHONE_CHANGE_CODE_INVALID"


def test_delivery_failure_is_503_and_burns_the_challenge(
    user: Browser, provider: FixedOtpProvider
) -> None:
    provider.fail = True
    response = ask(user)
    assert (response.status_code, code_of(response)) == (503, "OTP_DELIVERY_UNAVAILABLE")
    assert db_rows(db(), "SELECT 1 FROM phone_change_challenges WHERE consumed_at IS NULL") == []


def test_disabled_provider_is_503_for_every_number(client: TestClient, user: Browser) -> None:
    from app.auth.otp import DisabledOtpProvider

    client.app.state.auth._provider = DisabledOtpProvider()  # type: ignore[attr-defined]
    invite_phone(OTHER_PHONE)
    for phone in (NEW_PHONE, OTHER_PHONE):
        response = ask(user, phone)
        assert (response.status_code, code_of(response)) == (503, "OTP_DELIVERY_UNAVAILABLE")


def test_requests_are_rate_limited_per_account(
    make_app: Callable[..., TestClient], clock: FakeClock
) -> None:
    client = make_app(rate_limit_phone_change_per_user=2)
    browser = Browser(client)
    browser.login_ready()
    open_step_up(clock)
    assert ask(browser, "+916543210987").status_code == 202
    assert ask(browser, "+916543210986").status_code == 202
    limited = ask(browser, "+916543210985")
    assert (limited.status_code, code_of(limited)) == (429, "RATE_LIMITED")
    assert int(limited.headers["Retry-After"]) >= 1


def test_tester_sessions_cannot_change_numbers() -> None:
    from app.auth.tester import operation_allowed

    assert not operation_allowed("requestPhoneChange")
    assert not operation_allowed("confirmPhoneChange")


def test_migration_0016_round_trips(db_url: str, user: Browser) -> None:
    ask(user)
    command.downgrade(_alembic(db_url), "0015")
    assert (
        db_rows(db_url, "SELECT 1 FROM pg_tables WHERE tablename = 'phone_change_challenges'") == []
    )
    command.upgrade(_alembic(db_url), "head")
    assert db_rows(db_url, "SELECT 1 FROM pg_tables WHERE tablename = 'phone_change_challenges'")
