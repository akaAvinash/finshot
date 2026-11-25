"""Registration by one-time code, then sign-in with an authenticator code (real Postgres and Redis)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi.testclient import TestClient

from tests.integration.test_auth_stepup import audit_actions, code_for, enroll_and_confirm
from tests.support import OTHER_PHONE, PHONE, Browser, FakeClock, FixedOtpProvider, db_rows

MakeApp = Callable[..., TestClient]
LOGIN = "/api/v1/auth/login/totp"


def registered(client: TestClient, clock: FakeClock) -> str:
    """Register PHONE by one-time code, set up the authenticator, sign out."""
    browser = Browser(client)
    browser.login()
    secret = enroll_and_confirm(browser, clock)
    assert browser.post("/api/v1/auth/logout").status_code == 204
    clock.advance(31)
    return secret


def attempt(browser: Browser, phone: str, code: str) -> Any:
    browser.get_csrf()
    response = browser.post(LOGIN, json={"phone": phone, "code": code})
    if response.status_code == 200:
        browser.csrf = response.json()["csrfToken"]  # the new session-bound token
    return response


def body(response: Any) -> dict[str, Any]:
    data: dict[str, Any] = response.json()
    data.pop("requestId", None)
    return data


def test_registration_then_authenticator_login_opens_step_up(
    client: TestClient, clock: FakeClock, db_url: str
) -> None:
    secret = registered(client, clock)
    browser = Browser(client)
    response = attempt(browser, PHONE, code_for(secret, clock))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["user"]["totpEnabled"] is True
    assert data["session"]["stepUpUntil"] is not None
    assert data["csrfToken"]
    assert browser.get("/api/v1/auth/me").status_code == 200
    # The new session can do a step-up gated action without another code.
    other = Browser(client)
    clock.advance(31)
    assert attempt(other, PHONE, code_for(secret, clock)).status_code == 200
    ids = [
        r["id"] for r in browser.get("/api/v1/auth/sessions").json()["sessions"] if not r["current"]
    ]
    revoke = browser.send("DELETE", f"/api/v1/auth/sessions/{ids[0]}", headers=browser.headers())
    assert revoke.status_code == 204
    assert other.get("/api/v1/auth/me").status_code == 401
    rows = db_rows(
        db_url,
        "SELECT metadata_redacted AS m FROM audit_events WHERE action = 'login_succeeded'"
        " ORDER BY created_at DESC LIMIT 1",
    )
    assert rows[0]["m"]["method"] == "totp"
    assert "login_failed" not in audit_actions(db_url)


def test_a_code_works_once(client: TestClient, clock: FakeClock) -> None:
    secret = registered(client, clock)
    code = code_for(secret, clock)
    assert attempt(Browser(client), PHONE, code).status_code == 200
    replay = attempt(Browser(client), PHONE, code)
    assert replay.status_code == 401
    assert replay.json()["code"] == "INVALID_CREDENTIALS"


def test_every_failure_is_the_same_response(
    client: TestClient, clock: FakeClock, provider: FixedOtpProvider
) -> None:
    secret = registered(client, clock)
    good = code_for(secret, clock)
    wrong = "000000" if good != "000000" else "111111"

    # Invited, with a user, but no authenticator.
    plain = Browser(client)
    plain.login(phone=OTHER_PHONE)
    plain.post("/api/v1/auth/logout")

    responses = {
        "wrong code": attempt(Browser(client), PHONE, wrong),
        "no authenticator": attempt(Browser(client), OTHER_PHONE, good),
        "unknown number": attempt(Browser(client), "+919876599999", good),
    }
    statuses = {name: r.status_code for name, r in responses.items()}
    assert set(statuses.values()) == {401}, statuses
    bodies = [body(r) for r in responses.values()]
    assert all(b == bodies[0] for b in bodies), bodies
    assert bodies[0]["code"] == "INVALID_CREDENTIALS"


def test_revoked_invite_cannot_sign_in(client: TestClient, clock: FakeClock, db_url: str) -> None:
    secret = registered(client, clock)
    db_rows(db_url, "UPDATE invites SET revoked_at = now() WHERE phone_e164 = :p", p=PHONE)
    response = attempt(Browser(client), PHONE, code_for(secret, clock))
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_failures_are_throttled_per_phone_the_same_for_every_number(
    client: TestClient, clock: FakeClock
) -> None:
    secret = registered(client, clock)
    good = code_for(secret, clock)
    wrong = "000000" if good != "000000" else "111111"

    def burst(phone: str) -> list[int]:
        browser = Browser(client)
        browser.get_csrf()
        return [
            browser.post(LOGIN, json={"phone": phone, "code": wrong}).status_code for _ in range(7)
        ]

    real = burst(PHONE)
    unknown = burst("+919876599998")
    assert real == unknown == [401] * 5 + [429] * 2
    # Even the right code is refused while throttled.
    locked = attempt(Browser(client), PHONE, good)
    assert locked.status_code == 429
    assert locked.json()["code"] == "RATE_LIMITED"
    assert "Retry-After" in locked.headers


def test_a_successful_login_does_not_use_up_the_phone_allowance(
    client: TestClient, clock: FakeClock
) -> None:
    secret = registered(client, clock)
    for _ in range(7):
        clock.advance(31)
        assert attempt(Browser(client), PHONE, code_for(secret, clock)).status_code == 200


def test_a_one_time_code_cannot_start_a_session_once_an_authenticator_exists(
    client: TestClient, clock: FakeClock, provider: FixedOtpProvider, db_url: str
) -> None:
    # A code requested (and delivered) before the authenticator exists...
    early = Browser(client)
    early.get_csrf()
    challenge = early.request_otp(PHONE).json()["challengeId"]
    assert len(provider.deliveries) == 1
    registered(client, clock)
    # ...no longer starts a session, and stays unused.
    refused = early.verify(challenge, provider.code)
    assert refused.status_code == 401
    assert refused.json()["code"] == "INVALID_OTP"
    rows = db_rows(db_url, "SELECT consumed_at FROM otp_challenges WHERE id = :i", i=challenge)
    assert rows[0]["consumed_at"] is None
    # A new request answers the same 202 but sends nothing.
    before = len(provider.deliveries)
    late = Browser(client)
    late.get_csrf()
    assert late.request_otp(PHONE).status_code == 202
    assert len(provider.deliveries) == before


def test_concurrent_failures_never_exceed_the_phone_allowance(
    make_app: MakeApp, clock: FakeClock
) -> None:
    first = make_app()
    secret = registered(first, clock)
    good = code_for(secret, clock)
    wrong = "000000" if good != "000000" else "111111"
    browsers = [Browser(make_app()) for _ in range(10)]
    for b in browsers:
        b.get_csrf()
    barrier = threading.Barrier(len(browsers))

    def fire(b: Browser) -> int:
        barrier.wait()
        status: int = b.post(LOGIN, json={"phone": PHONE, "code": wrong}).status_code
        return status

    with ThreadPoolExecutor(len(browsers)) as pool:
        statuses = list(pool.map(fire, browsers))
    assert statuses.count(401) == 5, statuses  # the default allowance, never more
    assert statuses.count(429) == 5, statuses


def test_one_valid_code_redeemed_concurrently_starts_one_session(
    make_app: MakeApp, clock: FakeClock, db_url: str
) -> None:
    first = make_app()
    secret = registered(first, clock)
    code = code_for(secret, clock)
    # Four requests: within the phone allowance (5), so the losers fail on the code.
    browsers = [Browser(make_app()) for _ in range(4)]
    for b in browsers:
        b.get_csrf()
    barrier = threading.Barrier(len(browsers))

    def fire(b: Browser) -> tuple[int, str | None]:
        barrier.wait()
        response = b.post(LOGIN, json={"phone": PHONE, "code": code})
        return response.status_code, response.json().get("code")

    with ThreadPoolExecutor(len(browsers)) as pool:
        results = list(pool.map(fire, browsers))
    assert [r[0] for r in results].count(200) == 1, results
    assert [r for r in results if r[0] != 200] == [(401, "INVALID_CREDENTIALS")] * 3
    live = db_rows(db_url, "SELECT count(*) AS n FROM sessions WHERE revoked_at IS NULL")
    assert live[0]["n"] == 1


def test_a_failed_allowance_refund_does_not_fail_a_committed_login(
    client: TestClient, clock: FakeClock, monkeypatch: Any
) -> None:
    secret = registered(client, clock)

    async def broken(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("redis went away")

    monkeypatch.setattr(client.app.state.auth._limiter, "release", broken)
    browser = Browser(client)
    response = attempt(browser, PHONE, code_for(secret, clock))
    assert response.status_code == 200, response.text
    assert browser.cookie("__Host-tradeo_session")
    assert browser.cookie("__Host-tradeo_csrf")
    assert browser.get("/api/v1/auth/me").status_code == 200


def test_operator_reset_returns_the_account_to_registration(
    client: TestClient, clock: FakeClock, db_url: str, provider: FixedOtpProvider
) -> None:
    secret = registered(client, clock)
    db_rows(db_url, "DELETE FROM totp_credentials")
    assert attempt(Browser(client), PHONE, code_for(secret, clock)).status_code == 401
    again = Browser(client)
    again.login()
    assert again.get("/api/v1/auth/me").json()["user"]["totpEnabled"] is False


def test_login_needs_a_csrf_token_and_valid_body(client: TestClient, clock: FakeClock) -> None:
    secret = registered(client, clock)
    browser = Browser(client)
    no_token = browser.post(LOGIN, json={"phone": PHONE, "code": code_for(secret, clock)})
    assert no_token.status_code == 403
    assert no_token.json()["code"] == "CSRF_FAILED"
    browser.get_csrf()
    for bad in (
        {"phone": PHONE},
        {"phone": "12345", "code": "123456"},
        {"phone": PHONE, "code": "12345"},
        {"phone": PHONE, "code": "123456", "extra": 1},
    ):
        response = browser.post(LOGIN, json=bad)
        assert response.status_code == 400, bad
        assert response.json()["code"] == "INVALID_REQUEST"


def test_failed_attempts_are_audited_without_the_code(
    client: TestClient, clock: FakeClock, db_url: str
) -> None:
    secret = registered(client, clock)
    assert attempt(Browser(client), PHONE, "000000").status_code == 401
    rows = db_rows(
        db_url, "SELECT metadata_redacted AS m FROM audit_events WHERE action = 'login_failed'"
    )
    assert len(rows) == 1
    assert set(rows[0]["m"]) == {"ip_hash", "method"}
    assert secret not in str(rows)
