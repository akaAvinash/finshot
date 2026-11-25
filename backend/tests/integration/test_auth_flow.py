"""End-to-end auth behavior over real PostgreSQL and Redis."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.support import (
    ORIGIN,
    OTHER_PHONE,
    PHONE,
    Browser,
    FakeClock,
    FixedOtpProvider,
    RecordingRandomProvider,
    db_rows,
    new_id,
    parse_set_cookie,
)

pytestmark = pytest.mark.integration

SESSION = "__Host-tradeo_session"
CSRF = "__Host-tradeo_csrf"


def cookies_of(response: Any) -> list[dict[str, Any]]:
    return [parse_set_cookie(line) for line in response.headers.get_list("set-cookie")]


# --------------------------------------------------------------------- happy path


def test_full_login_session_logout_flow(browser: Browser) -> None:
    assert browser.get("/api/v1/auth/me").status_code == 401

    login = browser.login()
    body = login.json()
    assert body["user"]["phoneMasked"] == "+91******3210"
    assert body["user"]["displayName"] is None
    assert body["csrfToken"]
    assert set(body["session"]) == {"idleExpiresAt", "expiresAt", "stepUpUntil"}
    assert body["session"]["stepUpUntil"] is None
    assert PHONE not in login.text  # the full number is never returned

    me = browser.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["id"] == body["user"]["id"]
    assert "csrfToken" not in me.json()

    sessions = browser.get("/api/v1/auth/sessions").json()["sessions"]
    assert len(sessions) == 1 and sessions[0]["current"] is True

    out = browser.post("/api/v1/auth/logout")
    assert out.status_code == 204
    assert browser.get("/api/v1/auth/me").status_code == 401


def test_verify_returns_required_csrf_token_that_works_for_next_write(browser: Browser) -> None:
    browser.login()
    # The token from the verify response (stored by Browser) authorizes a write.
    assert browser.post("/api/v1/auth/logout-all").status_code == 204


def test_login_creates_user_once_per_phone(browser: Browser) -> None:
    browser.login()
    browser.post("/api/v1/auth/logout")
    browser.login()
    users = db_rows(_db(browser), "SELECT * FROM users")
    assert len(users) == 1
    assert users[0]["phone_verified_at"] is not None


def _db(browser: Browser) -> str:
    import os

    return os.environ["TEST_DATABASE_URL"]


# ------------------------------------------------------------------ cookie headers


def test_verify_sets_two_separate_hardened_cookies(browser: Browser) -> None:
    browser.get_csrf()
    challenge = browser.request_otp().json()
    response = browser.verify(challenge["challengeId"], "123456")
    lines = response.headers.get_list("set-cookie")
    assert len(lines) == 2  # two separate Set-Cookie fields, never combined
    session, csrf = (parse_set_cookie(x) for x in lines)
    assert (session["name"], csrf["name"]) == (SESSION, CSRF)  # session first
    for cookie in (session, csrf):
        attrs = cookie["attrs"]
        assert attrs["httponly"] is True
        assert attrs["secure"] is True
        assert str(attrs["samesite"]).lower() == "lax"
        assert attrs["path"] == "/"
        assert "domain" not in attrs  # host-only
        assert "max-age" not in attrs and "expires" not in attrs
    assert session["value"] != csrf["value"]


def test_logout_and_logout_all_send_two_clearing_fields(browser: Browser) -> None:
    for path in ("/api/v1/auth/logout", "/api/v1/auth/logout-all"):
        browser.login()
        response = browser.post(path)
        assert response.status_code == 204
        cleared = cookies_of(response)
        assert [c["name"] for c in cleared] == [SESSION, CSRF]
        for c in cleared:
            assert c["attrs"]["max-age"] == "0"
            assert "expires" in c["attrs"]
            assert c["attrs"]["secure"] is True and c["attrs"]["httponly"] is True
        assert browser.cookie(SESSION) is None and browser.cookie(CSRF) is None


def test_csrf_endpoint_sets_one_cookie_only_when_issuing(browser: Browser) -> None:
    first = browser.get_csrf()
    assert [c["name"] for c in cookies_of(first)] == [CSRF]
    again = browser.get_csrf()
    assert cookies_of(again) == []  # existing valid token is reused
    assert again.json()["csrfToken"] == first.json()["csrfToken"]
    assert first.json()["context"] == "pre_login"


# ----------------------------------------------------------------------- CSRF


def test_writes_without_valid_csrf_are_rejected(browser: Browser) -> None:
    browser.get_csrf()
    good = browser.csrf
    cases: dict[str, dict[str, str]] = {
        "no header": {"Origin": ORIGIN},
        "wrong header": browser.headers(csrf="x" * 60),
        "bad origin": browser.headers(origin="https://evil.example"),
    }
    for name, headers in cases.items():
        response = browser.request_otp(headers=headers)
        assert response.status_code == 403, name
        assert response.json()["code"] == "CSRF_FAILED", name
    assert browser.request_otp(headers=browser.headers(csrf=good)).status_code == 202


def test_csrf_header_must_match_cookie(browser: Browser, make_app: Any) -> None:
    other = Browser(browser.client)
    browser.get_csrf()
    other.get_csrf()
    assert browser.csrf != other.csrf
    # A validly signed token from another browser does not match this cookie.
    response = browser.request_otp(headers=browser.headers(csrf=other.csrf))
    assert response.status_code == 403


def test_no_csrf_cookie_means_rejected(browser: Browser) -> None:
    browser.get_csrf()
    token = browser.csrf
    browser.jar.clear()
    assert browser.request_otp(headers=browser.headers(csrf=token)).status_code == 403


def test_pre_login_token_cannot_authorize_session_writes(browser: Browser) -> None:
    browser.get_csrf()
    pre_login = browser.csrf
    challenge = browser.request_otp().json()
    browser.verify(challenge["challengeId"], "123456")
    session_token = browser.csrf
    assert session_token != pre_login
    # Old pre-login token no longer matches the (replaced) cookie, and its
    # context is wrong for a signed-in request.
    assert (
        browser.post("/api/v1/auth/logout-all", headers=browser.headers(csrf=pre_login)).status_code
        == 403
    )
    assert browser.post("/api/v1/auth/logout-all").status_code == 204


def test_session_token_is_bound_to_its_own_session(browser: Browser, client: TestClient) -> None:
    a, b, c = Browser(client), Browser(client), Browser(client)
    a.login()
    b.login(phone=OTHER_PHONE)
    c.get_csrf()  # a valid pre-login token
    b_session = b.cookie(SESSION)

    def forged(token: str | None) -> int:
        """B's session cookie with `token` in BOTH the CSRF cookie and the header,
        so the double-submit equality check passes and only binding can reject."""
        client.cookies.clear()
        response = client.post(
            "/api/v1/auth/logout-all",
            headers={
                "Cookie": f"{SESSION}={b_session}; {CSRF}={token}",
                "X-CSRF-Token": str(token),
                "Origin": ORIGIN,
            },
        )
        client.cookies.clear()
        return int(response.status_code)

    # A's validly signed session token, and a validly signed pre-login token,
    # are both rejected against B's session even though cookie == header.
    assert forged(a.csrf) == 403
    assert forged(c.csrf) == 403
    assert len(db_rows(_db(b), "SELECT 1 FROM sessions WHERE revoked_at IS NULL")) == 2
    # B's own matching pair is accepted.
    assert forged(b.csrf) == 204


def test_otp_verify_must_come_from_the_requesting_context(client: TestClient) -> None:
    victim, attacker = Browser(client), Browser(client)
    victim.get_csrf()
    challenge = victim.request_otp().json()
    attacker.get_csrf()
    response = attacker.verify(challenge["challengeId"], "123456")
    assert response.status_code == 401 and response.json()["code"] == "INVALID_OTP"
    # The attacker could not burn the victim's attempts, and the victim still logs in.
    rows = db_rows(_db(victim), "SELECT attempts FROM otp_challenges")
    assert rows[0]["attempts"] == 0
    assert victim.verify(challenge["challengeId"], "123456").status_code == 200


def test_logout_without_a_session_is_idempotent_with_pre_login_token(browser: Browser) -> None:
    browser.get_csrf()
    assert browser.post("/api/v1/auth/logout").status_code == 204


def test_logout_all_requires_a_session_before_csrf(browser: Browser) -> None:
    browser.get_csrf()
    assert browser.post("/api/v1/auth/logout-all").status_code == 401
    assert browser.post("/api/v1/auth/logout-all", headers={}).status_code == 401


# ----------------------------------------------- stale sessions: the recovery path


def test_csrf_endpoint_clears_stale_session_cookie_after_revocation(client: TestClient) -> None:
    a, b = Browser(client), Browser(client)
    a.login()
    # A second browser for the same user revokes everything.
    b.login()
    assert b.post("/api/v1/auth/logout-all").status_code == 204
    # A still holds its session cookie, but the server-side session is dead.
    assert a.cookie(SESSION) is not None
    assert a.get("/api/v1/auth/me").status_code == 401
    # Writes in the pre-login flow fail until it recovers...
    stale_token = a.csrf
    assert a.request_otp(headers=a.headers(csrf=stale_token)).status_code == 403

    recovery = a.get_csrf()
    body = recovery.json()
    assert body["context"] == "pre_login"
    names = [c["name"] for c in cookies_of(recovery)]
    assert names == [SESSION, CSRF]  # clear stale session first, then new CSRF
    cleared = cookies_of(recovery)[0]
    assert cleared["attrs"]["max-age"] == "0"
    assert a.cookie(SESSION) is None  # browser no longer holds stale auth state
    # ...and afterwards the OTP flow works.
    assert a.request_otp().status_code == 202


def test_csrf_endpoint_clears_stale_session_cookie_after_expiry(
    browser: Browser, clock: FakeClock
) -> None:
    browser.login()
    clock.advance(31 * 60)  # past the 30 minute idle timeout
    assert browser.get("/api/v1/auth/me").status_code == 401
    recovery = browser.get_csrf()
    assert recovery.json()["context"] == "pre_login"
    assert SESSION in [c["name"] for c in cookies_of(recovery)]
    assert browser.cookie(SESSION) is None


def test_csrf_endpoint_leaves_a_valid_session_cookie_alone(browser: Browser) -> None:
    browser.login()
    response = browser.get_csrf()
    assert response.json()["context"] == "session"
    assert cookies_of(response) == []  # nothing cleared or reissued
    assert browser.get("/api/v1/auth/me").status_code == 200


def test_csrf_endpoint_reissues_session_token_after_cookie_loss(browser: Browser) -> None:
    browser.login()
    del_token = browser.csrf
    # Simulate losing only the CSRF cookie.
    browser.jar = _without(browser.jar, CSRF)
    response = browser.get_csrf()
    assert response.json()["context"] == "session"
    assert [c["name"] for c in cookies_of(response)] == [CSRF]
    assert response.json()["csrfToken"] != del_token


def _without(jar: Any, name: str) -> Any:
    import httpx

    out = httpx.Cookies()
    for cookie in jar.jar:
        if cookie.name != name:
            out.jar.set_cookie(cookie)
    return out


def test_csrf_endpoint_without_session_cookie_sends_no_clear_field(browser: Browser) -> None:
    response = browser.get_csrf()
    assert [c["name"] for c in cookies_of(response)] == [CSRF]


# ------------------------------------------------------------------- OTP rules


def test_wrong_code_fails_and_counts_attempts(browser: Browser) -> None:
    browser.get_csrf()
    challenge = browser.request_otp().json()
    for _ in range(5):
        response = browser.verify(challenge["challengeId"], "000000")
        assert response.status_code == 401 and response.json()["code"] == "INVALID_OTP"
    # Locked: even the right code fails after 5 wrong attempts.
    assert browser.verify(challenge["challengeId"], "123456").status_code == 401
    rows = db_rows(_db(browser), "SELECT attempts, consumed_at FROM otp_challenges")
    assert rows[0]["attempts"] == 5 and rows[0]["consumed_at"] is None


def test_otp_expires(browser: Browser, clock: FakeClock) -> None:
    browser.get_csrf()
    challenge = browser.request_otp().json()
    clock.advance(5 * 60 + 1)
    assert browser.verify(challenge["challengeId"], "123456").status_code == 401


def test_otp_works_just_before_expiry(browser: Browser, clock: FakeClock) -> None:
    browser.get_csrf()
    challenge = browser.request_otp().json()
    clock.advance(5 * 60 - 1)
    # The pre-login CSRF token (30 min) is still valid.
    assert browser.verify(challenge["challengeId"], "123456").status_code == 200


def test_otp_replay_is_rejected(browser: Browser, client: TestClient) -> None:
    browser.get_csrf()
    challenge = browser.request_otp().json()
    assert browser.verify(challenge["challengeId"], "123456").status_code == 200
    # Replay from a fresh session of the same browser context is impossible
    # (the context changed); replay with the original pre-login context also fails.
    replay = Browser(client)
    replay.get_csrf()
    assert replay.verify(challenge["challengeId"], "123456").status_code == 401
    rows = db_rows(_db(browser), "SELECT consumed_at FROM otp_challenges")
    assert rows[0]["consumed_at"] is not None


def test_replay_in_same_pre_login_context_after_success_fails(browser: Browser) -> None:
    browser.get_csrf()
    pre_login_jar, pre_login_token = _clone(browser.jar), browser.csrf
    challenge = browser.request_otp().json()
    assert browser.verify(challenge["challengeId"], "123456").status_code == 200
    browser.post("/api/v1/auth/logout")
    # Go back to the original pre-login cookie/token and replay the same code.
    browser.jar, browser.csrf = pre_login_jar, pre_login_token
    response = browser.verify(challenge["challengeId"], "123456")
    assert response.status_code == 401 and response.json()["code"] == "INVALID_OTP"


def _clone(jar: Any) -> Any:
    import httpx

    out = httpx.Cookies()
    for cookie in jar.jar:
        out.jar.set_cookie(cookie)
    return out


def test_concurrent_verifies_with_the_right_code_create_one_session(client: TestClient) -> None:
    browser = Browser(client)
    browser.get_csrf()
    challenge = browser.request_otp().json()
    client = browser.activate()
    # Freeze the request credentials before any worker starts, then empty the
    # shared jar so a successful worker's Set-Cookie cannot change what others send.
    headers = {
        **browser.headers(),
        "Cookie": "; ".join(f"{c.name}={c.value}" for c in browser.jar.jar),
    }
    client.cookies.clear()

    def attempt(_: int) -> int:
        return client.post(
            "/api/v1/auth/otp/verify",
            json={"challengeId": challenge["challengeId"], "code": "123456"},
            headers=headers,
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, range(8)))
    assert statuses.count(200) == 1
    assert statuses.count(401) == 7
    assert len(db_rows(_db(browser), "SELECT 1 FROM sessions")) == 1


def test_otp_is_stored_hashed_and_sessions_store_only_digests(browser: Browser) -> None:
    login = browser.login()
    token = browser.cookie(SESSION)
    challenge_rows = db_rows(_db(browser), "SELECT * FROM otp_challenges")
    assert re.fullmatch(r"[0-9a-f]{64}", challenge_rows[0]["code_digest"])
    assert "123456" not in json.dumps(challenge_rows, default=str)
    assert challenge_rows[0]["request_ip_hash"] != "testclient"
    session_rows = db_rows(_db(browser), "SELECT * FROM sessions")
    assert token and token not in json.dumps(session_rows, default=str)
    assert re.fullmatch(r"[0-9a-f]{64}", session_rows[0]["session_digest"])
    assert login.json()["user"]["id"]


def test_otp_request_response_does_not_reveal_whether_an_account_exists(client: TestClient) -> None:
    known = Browser(client)
    known.login()
    known.post("/api/v1/auth/logout")
    fresh = Browser(client)
    fresh.get_csrf()
    issued: list[str] = []
    for browser, phone in ((known, PHONE), (fresh, "+919123456780")):
        browser.get_csrf()
        response = browser.request_otp(phone)
        assert response.status_code == 202
        assert set(response.json()) == {
            "challengeId",
            "expiresAt",
            "resendAvailableAt",
            "channel",
        }
        issued.append(response.json()["challengeId"])
    known_challenge, fresh_challenge = issued
    # Wrong codes against real challenges look identical for known and unknown phones.
    a = known.verify(known_challenge, "000000")
    b = fresh.verify(fresh_challenge, "000000")
    assert a.status_code == 401
    assert (a.status_code, a.json()["code"], a.json()["message"]) == (
        b.status_code,
        b.json()["code"],
        b.json()["message"],
    )


def test_validation_errors_are_400_with_contract_shape(browser: Browser) -> None:
    browser.get_csrf()
    for body in ({"phone": "9876543210"}, {"phone": "+14155550100"}, {}, {"phone": PHONE, "x": 1}):
        response = browser.post("/api/v1/auth/otp/request", json=body)
        assert response.status_code == 400, body
        assert response.json()["code"] == "INVALID_REQUEST"
    for body in (
        {"challengeId": "nope", "code": "123456"},
        {"challengeId": new_id(), "code": "12345"},
        {"challengeId": new_id(), "code": "abcdef"},
    ):
        assert browser.post("/api/v1/auth/otp/verify", json=body).status_code == 400


def test_disabled_account_cannot_log_in(browser: Browser) -> None:
    browser.login()
    browser.post("/api/v1/auth/logout")
    db_rows(_db(browser), "UPDATE users SET status = 'disabled'")
    browser.get_csrf()
    challenge = browser.request_otp().json()
    response = browser.verify(challenge["challengeId"], "123456")
    assert response.status_code == 401 and response.json()["code"] == "INVALID_OTP"


def test_delivery_failure_returns_503_and_leaves_no_challenge(
    browser: Browser, provider: FixedOtpProvider
) -> None:
    browser.get_csrf()
    provider.fail = True
    response = browser.request_otp()
    assert response.status_code == 503
    assert response.json()["code"] == "OTP_DELIVERY_UNAVAILABLE"
    assert db_rows(_db(browser), "SELECT 1 FROM otp_challenges") == []


# --------------------------------------------------------------- rate limiting


def test_rate_limit_per_phone_returns_429_with_retry_after(make_app: Any) -> None:
    client = make_app(rate_limit_otp_request_per_phone=2, rate_limit_otp_request_per_context=50)
    browser = Browser(client)
    browser.get_csrf()
    assert browser.request_otp().status_code == 202
    assert browser.request_otp().status_code == 202
    limited = browser.request_otp()
    assert limited.status_code == 429
    body = limited.json()
    assert body["code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) == body["retryAfterSeconds"] >= 1
    assert len(db_rows(_db(browser), "SELECT 1 FROM otp_challenges")) == 2
    # A different phone is not limited.
    assert browser.request_otp(OTHER_PHONE).status_code == 202


def test_rate_limit_per_ip_and_per_context(make_app: Any) -> None:
    client = make_app(rate_limit_otp_request_per_ip=3, rate_limit_otp_request_per_phone=50)
    a = Browser(client)
    a.get_csrf()
    for index in range(3):
        assert a.request_otp(f"+9198765432{index:02d}").status_code == 202
    assert a.request_otp("+919876543299").status_code == 429

    # Same browser context limit, with a generous IP limit.
    from_other = make_app(
        rate_limit_otp_request_per_context=2,
        rate_limit_otp_request_per_phone=50,
        rate_limit_otp_request_per_ip=50,
    )
    b = Browser(from_other)
    b.get_csrf()
    assert b.request_otp("+919876543201").status_code == 202
    assert b.request_otp("+919876543202").status_code == 202
    assert b.request_otp("+919876543203").status_code == 429


def test_throttled_caller_cannot_reserve_another_phones_cooldown(make_app: Any) -> None:
    client = make_app(
        otp_resend_cooldown_seconds=300,
        rate_limit_otp_request_per_context=1,
        rate_limit_otp_request_per_ip=50,
        rate_limit_otp_request_per_phone=50,
    )
    attacker, owner = Browser(client), Browser(client)
    attacker.get_csrf()
    assert attacker.request_otp(OTHER_PHONE).status_code == 202
    assert attacker.request_otp(PHONE).status_code == 429  # context limit, not cooldown
    owner.get_csrf()
    # The real owner of PHONE is not locked out by the throttled attempt.
    assert owner.request_otp(PHONE).status_code == 202


def test_resend_cooldown(make_app: Any) -> None:
    client = make_app(otp_resend_cooldown_seconds=30)
    browser = Browser(client)
    browser.get_csrf()
    first = browser.request_otp()
    assert first.status_code == 202
    second = browser.request_otp()
    assert second.status_code == 429
    assert 1 <= second.json()["retryAfterSeconds"] <= 30
    assert second.headers["Retry-After"] == str(second.json()["retryAfterSeconds"])


def test_verify_rate_limit_per_ip(make_app: Any) -> None:
    client = make_app(rate_limit_otp_verify_per_ip=3)
    browser = Browser(client)
    browser.get_csrf()
    challenge = browser.request_otp().json()
    codes = [browser.verify(challenge["challengeId"], "000000").status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]


def test_csrf_endpoint_is_rate_limited(make_app: Any) -> None:
    client = make_app(rate_limit_csrf_per_ip=2)
    browser = Browser(client)
    assert [browser.get_csrf().status_code for _ in range(3)] == [200, 200, 429]


def test_rate_limit_keys_do_not_contain_raw_phone_or_ip(browser: Browser) -> None:
    import os

    import redis as redis_sync

    browser.get_csrf()
    browser.request_otp()
    keys = [k.decode() for k in redis_sync.Redis.from_url(os.environ["TEST_REDIS_URL"]).keys("*")]
    assert keys
    assert not [k for k in keys if "9876543210" in k or "testclient" in k]


def test_forwarded_for_is_ignored_unless_proxy_hops_configured(make_app: Any) -> None:
    spoof = {"X-Forwarded-For": "1.2.3.4"}
    # Default (0 hops): header ignored, so one socket peer shares one IP bucket.
    plain = Browser(make_app(rate_limit_otp_request_per_ip=1, rate_limit_otp_request_per_phone=50))
    plain.get_csrf()
    assert (
        plain.request_otp("+919876543201", headers={**plain.headers(), **spoof}).status_code == 202
    )
    assert (
        plain.request_otp(
            "+919876543202", headers={**plain.headers(), "X-Forwarded-For": "5.6.7.8"}
        ).status_code
        == 429
    )
    # One trusted hop: the last entry (appended by the trusted proxy) is the client.
    proxied = Browser(
        make_app(
            rate_limit_otp_request_per_ip=1,
            rate_limit_otp_request_per_phone=50,
            trusted_proxy_hops=1,
        )
    )
    proxied.get_csrf()
    assert (
        proxied.request_otp(
            "+919876543203", headers={**proxied.headers(), "X-Forwarded-For": "9.9.9.9, 1.1.1.1"}
        ).status_code
        == 202
    )
    assert (
        proxied.request_otp(
            "+919876543204", headers={**proxied.headers(), "X-Forwarded-For": "8.8.8.8, 2.2.2.2"}
        ).status_code
        == 202
    )
    assert (
        proxied.request_otp(
            "+919876543205", headers={**proxied.headers(), "X-Forwarded-For": "7.7.7.7, 1.1.1.1"}
        ).status_code
        == 429
    )


# --------------------------------------------------------------------- sessions


def test_session_idle_expiry(browser: Browser, clock: FakeClock) -> None:
    browser.login()
    clock.advance(25 * 60)
    assert browser.get("/api/v1/auth/me").status_code == 200  # activity extends idle
    clock.advance(25 * 60)
    assert browser.get("/api/v1/auth/me").status_code == 200
    clock.advance(31 * 60)  # no activity past the 30 minute idle timeout
    assert browser.get("/api/v1/auth/me").status_code == 401


def test_session_absolute_expiry_ends_an_active_session(browser: Browser, clock: FakeClock) -> None:
    browser.login()
    for _ in range(28):  # stay active for 700 minutes, under the 12 hour limit
        clock.advance(25 * 60)
        assert browser.get("/api/v1/auth/me").status_code == 200
    clock.advance(25 * 60)  # 725 minutes: past the absolute limit despite activity
    assert browser.get("/api/v1/auth/me").status_code == 401


def test_idle_expiry_is_capped_by_absolute_expiry(browser: Browser, clock: FakeClock) -> None:
    body = browser.login().json()["session"]
    assert body["idleExpiresAt"] < body["expiresAt"]
    me = browser.get("/api/v1/auth/me").json()["session"]
    assert me["idleExpiresAt"] <= me["expiresAt"]


def test_idle_expiry_equals_absolute_expiry_near_the_end(
    browser: Browser, clock: FakeClock
) -> None:
    browser.login()
    for _ in range(28):  # 700 minutes of activity; 20 minutes left of 12 hours
        clock.advance(25 * 60)
        assert browser.get("/api/v1/auth/me").status_code == 200
    session = browser.get("/api/v1/auth/me").json()["session"]
    # Idle would be +30 minutes, but the session ends sooner, so the cap applies.
    assert session["idleExpiresAt"] == session["expiresAt"]


def test_short_idle_ttl_is_renewed_by_regular_activity(make_app: Any, clock: FakeClock) -> None:
    client = make_app(session_idle_ttl_seconds=60)
    browser = Browser(client)
    browser.login()
    for _ in range(6):  # a request every 30 s for 3 minutes, idle TTL is 60 s
        clock.advance(30)
        assert browser.get("/api/v1/auth/me").status_code == 200
    clock.advance(61)
    assert browser.get("/api/v1/auth/me").status_code == 401


def test_login_rotates_an_existing_session(browser: Browser) -> None:
    browser.login()
    old = browser.cookie(SESSION)
    (old_row,) = db_rows(_db(browser), "SELECT id FROM sessions")
    challenge = browser.request_otp(OTHER_PHONE).json()
    browser.verify(challenge["challengeId"], "123456")
    assert browser.cookie(SESSION) != old
    rows = {
        r["id"]: r["revoked_at"]
        for r in db_rows(_db(browser), "SELECT id, revoked_at FROM sessions")
    }
    assert len(rows) == 2
    assert rows[old_row["id"]] is not None
    assert [v for k, v in rows.items() if k != old_row["id"]] == [None]


def test_tenant_isolation_for_sessions(client: TestClient) -> None:
    alice, alice2, bob = Browser(client), Browser(client), Browser(client)
    alice.login()
    alice2.login()
    bob.login(phone=OTHER_PHONE)

    alice_sessions = alice.get("/api/v1/auth/sessions").json()["sessions"]
    bob_sessions = bob.get("/api/v1/auth/sessions").json()["sessions"]
    assert len(alice_sessions) == 2 and len(bob_sessions) == 1
    assert {s["id"] for s in alice_sessions}.isdisjoint({s["id"] for s in bob_sessions})
    assert [s["current"] for s in alice_sessions].count(True) == 1
    assert (
        bob.get("/api/v1/auth/me").json()["user"]["id"]
        != alice.get("/api/v1/auth/me").json()["user"]["id"]
    )

    # Alice logging out everywhere does not touch Bob.
    assert alice.post("/api/v1/auth/logout-all").status_code == 204
    assert alice2.get("/api/v1/auth/me").status_code == 401
    assert bob.get("/api/v1/auth/me").status_code == 200
    assert len(bob.get("/api/v1/auth/sessions").json()["sessions"]) == 1


def test_sessions_list_excludes_revoked_and_expired(client: TestClient, clock: FakeClock) -> None:
    a, b = Browser(client), Browser(client)
    a.login()
    b.login()
    assert len(a.get("/api/v1/auth/sessions").json()["sessions"]) == 2
    b.post("/api/v1/auth/logout")
    assert len(a.get("/api/v1/auth/sessions").json()["sessions"]) == 1


def test_sessions_list_excludes_idle_expired_sessions(client: TestClient, clock: FakeClock) -> None:
    stale, live = Browser(client), Browser(client)
    stale.login()
    clock.advance(31 * 60)  # `stale` is now past its idle timeout but never revoked
    live.login()
    sessions = live.get("/api/v1/auth/sessions").json()["sessions"]
    assert len(sessions) == 1 and sessions[0]["current"] is True
    assert (
        db_rows(_db(live), "SELECT count(*) AS n FROM sessions WHERE revoked_at IS NULL")[0]["n"]
        == 2
    )


def test_session_summary_has_no_secrets(browser: Browser) -> None:
    browser.login()
    token = browser.cookie(SESSION)
    text = browser.get("/api/v1/auth/sessions").text
    assert token and token not in text
    assert "digest" not in text.lower()


# ------------------------------------------------------------------------ audit


def test_audit_events_record_actions_without_secrets(browser: Browser, client: TestClient) -> None:
    browser.login()
    session_token = browser.cookie(SESSION)
    assert session_token and len(session_token) >= 32
    assert browser.post("/api/v1/auth/logout-all").status_code == 204
    wrong = Browser(client)
    wrong.get_csrf()
    challenge = wrong.request_otp().json()
    wrong.verify(challenge["challengeId"], "000000")

    rows = db_rows(_db(browser), "SELECT * FROM audit_events ORDER BY created_at, action")
    actions = [r["action"] for r in rows]
    for expected in ("otp_requested", "login_succeeded", "logout_all", "otp_verify_failed"):
        assert expected in actions
    blob = json.dumps(rows, default=str)
    for secret in (PHONE, "9876543210", "123456", session_token):
        assert secret not in blob
    login = next(r for r in rows if r["action"] == "login_succeeded")
    assert login["user_id"] is not None and login["actor"].startswith("user:")


# ----------------------------------------------------------------- logs / output


def test_otp_codes_never_reach_application_logs(
    make_app: Any, provider: FixedOtpProvider, capfd: pytest.CaptureFixture[str]
) -> None:
    provider.code = "482913"
    browser = Browser(make_app())
    browser.login(code="482913")
    out = capfd.readouterr()
    assert "482913" not in out.out + out.err


def test_default_provider_is_disabled_so_otp_request_is_503(
    make_settings: Any, db_url: str
) -> None:
    import os

    from app.main import create_app

    settings = make_settings(database_url=db_url, redis_url=os.environ["TEST_REDIS_URL"])
    with TestClient(create_app(settings), base_url="https://testserver") as raw:
        browser = Browser(raw)
        browser.get_csrf()
        response = browser.request_otp()
    assert response.status_code == 503
    assert response.json()["code"] == "OTP_DELIVERY_UNAVAILABLE"


def test_console_provider_refuses_without_a_terminal(
    make_settings: Any, db_url: str, capfd: pytest.CaptureFixture[str]
) -> None:
    import os

    from app.main import create_app

    settings = make_settings(
        app_env="development",
        otp_provider="console",
        database_url=db_url,
        redis_url=os.environ["TEST_REDIS_URL"],
        otp_resend_cooldown_seconds=0,
    )
    with TestClient(create_app(settings), base_url="https://testserver") as raw:
        browser = Browser(raw)
        browser.get_csrf()
        response = browser.request_otp()
    out = capfd.readouterr()
    assert response.status_code == 503  # pytest's stderr is not a TTY
    assert not re.search(r"\b[0-9]{6}\b", out.out + out.err.replace("0123456789", ""))


def test_random_provider_flow(make_settings: Any, db_url: str, clock: FakeClock) -> None:
    import os

    from app.main import create_app

    rec = RecordingRandomProvider()
    settings = make_settings(
        database_url=db_url,
        redis_url=os.environ["TEST_REDIS_URL"],
        otp_resend_cooldown_seconds=0,
    )
    with TestClient(
        create_app(settings, otp_provider=rec, clock=clock), base_url="https://testserver"
    ) as raw:
        browser = Browser(raw)
        browser.get_csrf()
        challenge = browser.request_otp().json()
        code = rec.deliveries[-1][1]
        assert re.fullmatch(r"[0-9]{6}", code)
        wrong = "000000" if code != "000000" else "111111"
        assert browser.verify(challenge["challengeId"], wrong).status_code == 401
        assert browser.verify(challenge["challengeId"], code).status_code == 200
