"""Recovery codes: create, sign in with one, and how they die (real Postgres and Redis)."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi.testclient import TestClient

from tests.integration.test_auth_stepup import audit_actions, code_for, enroll_and_confirm
from tests.support import PHONE, Browser, FakeClock, db_rows

MakeApp = Callable[..., TestClient]
CODES = "/api/v1/auth/totp/recovery-codes"
LOGIN = "/api/v1/auth/login/recovery"
CODE_RE = re.compile(r"^[A-Z2-7]{5}-[A-Z2-7]{5}$")


def signed_in_with_codes(client: TestClient, clock: FakeClock) -> tuple[Browser, str, list[str]]:
    """Register, enrol the authenticator and create recovery codes (session stays open)."""
    browser = Browser(client)
    browser.login()
    secret = enroll_and_confirm(browser, clock)
    response = browser.post(CODES)
    assert response.status_code == 200, response.text
    return browser, secret, response.json()["codes"]


def recover(browser: Browser, phone: str, code: str) -> Any:
    browser.get_csrf()
    response = browser.post(LOGIN, json={"phone": phone, "recoveryCode": code})
    if response.status_code == 200:
        browser.csrf = response.json()["csrfToken"]
    return response


def test_codes_are_ten_distinct_and_stored_only_as_digests(
    client: TestClient, clock: FakeClock, db_url: str
) -> None:
    browser, _, codes = signed_in_with_codes(client, clock)
    assert len(set(codes)) == 10 and all(CODE_RE.match(c) for c in codes)
    rows = db_rows(db_url, "SELECT digest FROM recovery_codes")
    assert len(rows) == 10
    assert not {c for c in codes} & {r["digest"] for r in rows}
    assert "totp.recovery_codes_created" in audit_actions(db_url)
    assert not any(c in str(db_rows(db_url, "SELECT * FROM audit_events")) for c in codes)
    assert browser.get("/api/v1/auth/me").status_code == 200


def test_regenerating_replaces_every_earlier_code(client: TestClient, clock: FakeClock) -> None:
    browser, _, old = signed_in_with_codes(client, clock)
    new = browser.post(CODES).json()["codes"]
    assert not set(old) & set(new)
    assert recover(Browser(client), PHONE, old[0]).status_code == 401
    assert recover(Browser(client), PHONE, new[0]).status_code == 200


def test_creating_codes_needs_step_up_and_csrf(client: TestClient, clock: FakeClock) -> None:
    browser, secret, _ = signed_in_with_codes(client, clock)
    assert browser.send("POST", CODES, headers=browser.headers(csrf="x")).status_code == 403
    clock.advance(1000)  # the step-up window closes, the session stays
    browser.get_csrf()
    closed = browser.post(CODES)
    assert closed.status_code == 403
    assert closed.json()["code"] == "STEP_UP_REQUIRED"
    assert (
        browser.post(
            CODES.replace("totp/recovery-codes", "step-up"), json={"code": code_for(secret, clock)}
        ).status_code
        == 200
    )
    assert browser.post(CODES).status_code == 200


def test_creating_codes_needs_an_authenticator(client: TestClient) -> None:
    browser = Browser(client)
    browser.login()
    assert browser.post(CODES).status_code == 403  # no step-up window without an authenticator


def test_recovery_sign_in_spends_the_code_and_removes_the_authenticator(
    client: TestClient, clock: FakeClock, db_url: str
) -> None:
    _, secret, codes = signed_in_with_codes(client, clock)
    fresh = Browser(client)
    response = recover(fresh, PHONE, codes[0])
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["user"]["totpEnabled"] is False
    assert data["session"]["stepUpUntil"] is None
    assert db_rows(db_url, "SELECT 1 FROM totp_credentials") == []
    assert db_rows(db_url, "SELECT 1 FROM recovery_codes") == []
    assert "totp.reset_by_recovery_code" in audit_actions(db_url)
    # The new session can enrol a new authenticator straight away.
    assert fresh.post("/api/v1/auth/totp/enroll").status_code == 200
    # The old authenticator and every other code no longer work.
    assert recover(Browser(client), PHONE, codes[1]).status_code == 401
    clock.advance(31)
    other = Browser(client)
    other.get_csrf()
    assert (
        other.post(
            "/api/v1/auth/login/totp", json={"phone": PHONE, "code": code_for(secret, clock)}
        ).status_code
        == 401
    )


def test_a_code_works_once_and_every_failure_looks_the_same(
    client: TestClient, clock: FakeClock
) -> None:
    _, _, codes = signed_in_with_codes(client, clock)
    assert recover(Browser(client), PHONE, codes[0]).status_code == 200
    replay = recover(Browser(client), PHONE, codes[0])
    unknown = recover(Browser(client), "+919876500000", codes[1])
    wrong = recover(Browser(client), PHONE, "AAAAA-AAAAA")
    for r in (replay, unknown, wrong):
        assert r.status_code == 401
        assert r.json()["code"] == "INVALID_CREDENTIALS"
    assert replay.json()["message"] == unknown.json()["message"] == wrong.json()["message"]


def test_disabling_the_authenticator_invalidates_the_codes(
    client: TestClient, clock: FakeClock, db_url: str
) -> None:
    browser, secret, codes = signed_in_with_codes(client, clock)
    clock.advance(31)
    disabled = browser.post("/api/v1/auth/totp/disable", json={"code": code_for(secret, clock)})
    assert disabled.status_code == 204
    assert db_rows(db_url, "SELECT 1 FROM recovery_codes") == []
    # A later authenticator does not bring the old codes back.
    clock.advance(31)
    assert browser.post("/api/v1/auth/totp/enroll").status_code == 200
    assert recover(Browser(client), PHONE, codes[0]).status_code == 401


def test_operator_reset_invalidates_the_codes(
    client: TestClient, clock: FakeClock, db_url: str
) -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.auth import admin

    _, _, codes = signed_in_with_codes(client, clock)

    async def go() -> None:
        engine = create_async_engine(db_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                await admin.reset_totp(db, PHONE, clock())
        finally:
            await engine.dispose()

    asyncio.run(go())
    assert db_rows(db_url, "SELECT 1 FROM recovery_codes") == []
    assert recover(Browser(client), PHONE, codes[0]).status_code == 401


def test_confirming_a_new_authenticator_clears_stale_codes(
    client: TestClient, clock: FakeClock, db_url: str
) -> None:
    browser, _, _ = signed_in_with_codes(client, clock)
    # Simulate a stale set left behind, then enrol again after the authenticator is gone.
    db_rows(db_url, "DELETE FROM totp_credentials")
    assert db_rows(db_url, "SELECT 1 FROM recovery_codes")
    clock.advance(31)
    browser.get_csrf()
    enroll_and_confirm(browser, clock)
    assert db_rows(db_url, "SELECT 1 FROM recovery_codes") == []


def test_one_code_redeemed_concurrently_starts_one_session(
    make_app: MakeApp, clock: FakeClock, db_url: str
) -> None:
    first = make_app()
    _, _, codes = signed_in_with_codes(first, clock)
    browsers = [Browser(make_app()) for _ in range(4)]
    for b in browsers:
        b.get_csrf()
    barrier = threading.Barrier(len(browsers))

    def fire(b: Browser) -> int:
        barrier.wait()
        status: int = b.post(LOGIN, json={"phone": PHONE, "recoveryCode": codes[0]}).status_code
        return status

    with ThreadPoolExecutor(len(browsers)) as pool:
        statuses = list(pool.map(fire, browsers))
    assert statuses.count(200) == 1, statuses
    assert statuses.count(401) == 3, statuses
    rows = db_rows(
        db_url,
        "SELECT 1 FROM audit_events WHERE action = 'login_succeeded'"
        " AND metadata_redacted->>'method' = 'recovery'",
    )
    assert len(rows) == 1


def test_failures_share_the_authenticator_allowance(make_app: MakeApp, clock: FakeClock) -> None:
    app = make_app(rate_limit_totp_per_user=3)
    _, secret, _ = signed_in_with_codes(app, clock)
    b = Browser(app)
    statuses = [recover(b, PHONE, "AAAAA-AAAAA").status_code for _ in range(4)]
    assert statuses == [401, 401, 401, 429]
    clock.advance(31)
    totp = Browser(app)
    totp.get_csrf()
    blocked = totp.post(
        "/api/v1/auth/login/totp", json={"phone": PHONE, "code": code_for(secret, clock)}
    )
    assert blocked.status_code == 429  # one allowance for both ways in


def test_bad_bodies_are_rejected(client: TestClient) -> None:
    b = Browser(client)
    b.get_csrf()
    for payload in (
        {"phone": PHONE},
        {"phone": PHONE, "recoveryCode": "aaaaa-aaaaa"},
        {"phone": PHONE, "recoveryCode": "AAAAAAAAAA"},
        {"phone": PHONE, "recoveryCode": "AAAAA-AAAAA", "extra": 1},
    ):
        assert b.post(LOGIN, json=payload).status_code == 400


def test_different_codes_redeemed_concurrently_never_deadlock(
    make_app: MakeApp, clock: FakeClock, db_url: str
) -> None:
    first = make_app()
    _, _, codes = signed_in_with_codes(first, clock)
    browsers = [Browser(make_app()) for _ in range(4)]
    for b in browsers:
        b.get_csrf()
    barrier = threading.Barrier(len(browsers))

    def fire(args: tuple[Browser, str]) -> int:
        b, code = args
        barrier.wait()
        status: int = b.post(LOGIN, json={"phone": PHONE, "recoveryCode": code}).status_code
        return status

    with ThreadPoolExecutor(len(browsers)) as pool:
        statuses = list(pool.map(fire, zip(browsers, codes[:4], strict=True)))
    # Exactly one wins; the rest find the authenticator and codes already gone.
    assert statuses.count(200) == 1, statuses
    assert statuses.count(401) == 3, statuses
    assert db_rows(db_url, "SELECT 1 FROM recovery_codes") == []


def test_redeeming_while_regenerating_ends_in_one_consistent_state(
    make_app: MakeApp, clock: FakeClock, db_url: str
) -> None:
    app = make_app()
    owner, _, codes = signed_in_with_codes(app, clock)
    other = Browser(make_app())
    other.get_csrf()
    barrier = threading.Barrier(2)

    def regenerate() -> tuple[int, str | None]:
        barrier.wait()
        response = owner.post(CODES)
        error: str | None = None if response.status_code == 200 else response.json()["code"]
        return response.status_code, error

    def redeem() -> int:
        barrier.wait()
        status: int = other.post(LOGIN, json={"phone": PHONE, "recoveryCode": codes[0]}).status_code
        return status

    with ThreadPoolExecutor(2) as pool:
        regen, login = pool.submit(regenerate), pool.submit(redeem)
        results = (regen.result(), login.result())
    assert results[1] in (200, 401), results  # never a 500
    # 403 STEP_UP_REQUIRED when the sign-in committed first and closed this
    # session's step-up window; 409 if it got past that check but lost the lock.
    assert results[0] in {
        (200, None),
        (403, "STEP_UP_REQUIRED"),
        (409, "TOTP_NOT_ENROLLED"),
    }, results
    count = len(db_rows(db_url, "SELECT 1 FROM recovery_codes"))
    has_authenticator = bool(db_rows(db_url, "SELECT 1 FROM totp_credentials"))
    # Either the sign-in won (no authenticator, no codes) or regeneration finished first
    # (code gone, authenticator kept with ten new codes).
    assert (has_authenticator, count) in {(False, 0), (True, 10)}, (has_authenticator, count)
