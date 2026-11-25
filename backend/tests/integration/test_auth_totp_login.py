"""Registration by one-time code, then sign-in with an authenticator code (real Postgres and Redis)."""

from __future__ import annotations

from collections.abc import Callable
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
    client: TestClient, clock: FakeClock, provider: FixedOtpProvider
) -> None:
    registered(client, clock)
    before = len(provider.deliveries)
    browser = Browser(client)
    browser.get_csrf()
    challenge = browser.request_otp(PHONE)
    assert challenge.status_code == 202  # same response as always
    assert len(provider.deliveries) == before  # nothing sent
    response = browser.verify(challenge.json()["challengeId"], provider.code)
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_OTP"
    # A code requested before the authenticator existed is refused too.


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
