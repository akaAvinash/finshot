"""TOTP enrolment, step-up, invite-only access and OTP spend limits (real Postgres and Redis)."""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from app.auth import totp
from tests.support import OTHER_PHONE, PHONE, Browser, FakeClock, FixedOtpProvider, db_rows

MakeApp = Callable[..., TestClient]


def code_for(secret_b32: str, clock: FakeClock, offset: int = 0) -> str:
    secret = base64.b32decode(secret_b32)
    return totp.code_at(secret, totp.current_step(clock.now.timestamp()) + offset)


def enroll_and_confirm(browser: Browser, clock: FakeClock) -> str:
    enrolled = browser.post("/api/v1/auth/totp/enroll")
    assert enrolled.status_code == 200, enrolled.text
    secret = enrolled.json()["secret"]
    confirmed = browser.post("/api/v1/auth/totp/confirm", json={"code": code_for(secret, clock)})
    assert confirmed.status_code == 200, confirmed.text
    return secret


def audit_actions(db_url: str) -> list[str]:
    rows = db_rows(db_url, "SELECT action FROM audit_events ORDER BY created_at, id")
    return [r["action"] for r in rows]


# ------------------------------------------------------------------ invites


def test_uninvited_number_gets_the_same_response_and_no_delivery(
    browser: Browser, provider: FixedOtpProvider
) -> None:
    browser.get_csrf()
    invited = browser.request_otp(PHONE)
    uninvited = browser.request_otp(OTHER_PHONE, invite=False)
    assert invited.status_code == uninvited.status_code == 202
    assert set(invited.json()) == set(uninvited.json())
    assert [d[0] for d in provider.deliveries] == [PHONE]


def test_uninvited_number_cannot_verify_even_with_the_known_code(
    browser: Browser, provider: FixedOtpProvider
) -> None:
    browser.get_csrf()
    challenge = browser.request_otp(OTHER_PHONE, invite=False).json()["challengeId"]
    response = browser.verify(challenge, provider.code)
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_OTP"


def test_revoked_invite_blocks_verification(browser: Browser, db_url: str) -> None:
    browser.get_csrf()
    challenge = browser.request_otp(PHONE).json()["challengeId"]
    db_rows(db_url, "UPDATE invites SET revoked_at = now() WHERE phone_e164 = :p", p=PHONE)
    assert browser.verify(challenge, "123456").status_code == 401


# --------------------------------------------------------------- spend caps


def test_daily_delivery_cap_fails_closed_with_503(
    make_app: MakeApp, provider: FixedOtpProvider
) -> None:
    browser = Browser(make_app(otp_daily_delivery_limit_per_phone=2))
    browser.get_csrf()
    assert browser.request_otp(PHONE).status_code == 202
    assert browser.request_otp(PHONE).status_code == 202
    capped = browser.request_otp(PHONE)
    assert capped.status_code == 503
    assert capped.json()["code"] == "OTP_DELIVERY_UNAVAILABLE"
    assert len(provider.deliveries) == 2


def test_global_cap_applies_across_numbers(make_app: MakeApp, provider: FixedOtpProvider) -> None:
    browser = Browser(make_app(otp_daily_delivery_limit=1))
    browser.get_csrf()
    assert browser.request_otp(PHONE).status_code == 202
    assert browser.request_otp(OTHER_PHONE).status_code == 503
    assert len(provider.deliveries) == 1


def test_uninvited_requests_spend_nothing(make_app: MakeApp, provider: FixedOtpProvider) -> None:
    browser = Browser(make_app(otp_daily_delivery_limit=1))
    browser.get_csrf()
    for _ in range(3):
        assert browser.request_otp(OTHER_PHONE, invite=False).status_code == 202
    assert browser.request_otp(PHONE).status_code == 202


# ------------------------------------------------------------------- TOTP


def test_enroll_confirm_step_up_and_disable(
    browser: Browser, clock: FakeClock, db_url: str
) -> None:
    browser.login()
    assert browser.get("/api/v1/auth/me").json()["user"]["totpEnabled"] is False
    secret = enroll_and_confirm(browser, clock)

    me = browser.get("/api/v1/auth/me").json()
    assert me["user"]["totpEnabled"] is True
    assert me["session"]["stepUpUntil"] is not None

    # The secret is sealed at rest, never stored in the clear.
    stored = db_rows(db_url, "SELECT secret_enc FROM totp_credentials")[0]["secret_enc"]
    assert base64.b32decode(secret) not in bytes(stored)

    clock.advance(31)
    stepped = browser.post("/api/v1/auth/step-up", json={"code": code_for(secret, clock)})
    assert stepped.status_code == 200 and stepped.json()["totpEnabled"] is True

    clock.advance(31)
    disabled = browser.post("/api/v1/auth/totp/disable", json={"code": code_for(secret, clock)})
    assert disabled.status_code == 204
    after = browser.get("/api/v1/auth/me").json()
    assert after["user"]["totpEnabled"] is False and after["session"]["stepUpUntil"] is None
    assert {"totp.enrollment_started", "totp.enabled", "totp.step_up", "totp.disabled"} <= set(
        audit_actions(db_url)
    )


def test_wrong_code_is_rejected_and_audited(
    browser: Browser, clock: FakeClock, db_url: str
) -> None:
    browser.login()
    browser.post("/api/v1/auth/totp/enroll")
    bad = browser.post("/api/v1/auth/totp/confirm", json={"code": "000000"})
    assert bad.status_code == 422 and bad.json()["code"] == "INVALID_TOTP"
    assert "totp.confirm_failed" in audit_actions(db_url)
    assert browser.get("/api/v1/auth/me").json()["user"]["totpEnabled"] is False


def test_a_code_cannot_be_replayed(browser: Browser, clock: FakeClock) -> None:
    browser.login()
    secret = enroll_and_confirm(browser, clock)  # consumed this step's code
    replay = browser.post("/api/v1/auth/step-up", json={"code": code_for(secret, clock)})
    assert replay.status_code == 422
    clock.advance(30)
    assert (
        browser.post("/api/v1/auth/step-up", json={"code": code_for(secret, clock)}).status_code
        == 200
    )


def test_step_up_window_expires_and_never_outlives_the_session(
    browser: Browser, clock: FakeClock
) -> None:
    browser.login()
    secret = enroll_and_confirm(browser, clock)
    clock.advance(601)
    assert browser.get("/api/v1/auth/me").json()["session"]["stepUpUntil"] is None
    assert (
        browser.post("/api/v1/auth/step-up", json={"code": code_for(secret, clock)}).status_code
        == 200
    )


def test_step_up_without_enrolment_is_409(browser: Browser) -> None:
    browser.login()
    response = browser.post("/api/v1/auth/step-up", json={"code": "123456"})
    assert response.status_code == 409 and response.json()["code"] == "TOTP_NOT_ENROLLED"


def test_confirm_without_pending_enrolment_is_409(browser: Browser) -> None:
    browser.login()
    response = browser.post("/api/v1/auth/totp/confirm", json={"code": "123456"})
    assert response.status_code == 409 and response.json()["code"] == "TOTP_NOT_PENDING"


def test_enrolling_over_an_active_authenticator_is_409(browser: Browser, clock: FakeClock) -> None:
    browser.login()
    enroll_and_confirm(browser, clock)
    again = browser.post("/api/v1/auth/totp/enroll")
    assert again.status_code == 409 and again.json()["code"] == "TOTP_ALREADY_ENROLLED"


def test_enrolment_needs_a_recent_sign_in(browser: Browser, clock: FakeClock) -> None:
    browser.login()
    clock.advance(1000)  # older than totp_enroll_recent_seconds (900)
    response = browser.post("/api/v1/auth/totp/enroll")
    assert response.status_code == 403 and response.json()["code"] == "STEP_UP_REQUIRED"


def test_pending_enrolment_expires(browser: Browser, clock: FakeClock) -> None:
    browser.login()
    secret = browser.post("/api/v1/auth/totp/enroll").json()["secret"]
    clock.advance(901)
    response = browser.post("/api/v1/auth/totp/confirm", json={"code": code_for(secret, clock)})
    assert response.status_code in (401, 409)
    assert browser.get("/api/v1/auth/me").json()["user"]["totpEnabled"] is False


def test_totp_attempts_are_rate_limited(make_app: MakeApp) -> None:
    browser = Browser(make_app(rate_limit_totp_per_user=3))
    browser.login()
    browser.post("/api/v1/auth/totp/enroll")
    codes = [
        browser.post("/api/v1/auth/totp/confirm", json={"code": "000000"}).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [422, 422, 422]
    assert codes[-1] == 429


def test_totp_routes_need_csrf_and_a_session(client: TestClient, browser: Browser) -> None:
    assert client.post("/api/v1/auth/step-up", json={"code": "123456"}).status_code in (401, 403)
    browser.login()
    no_csrf = browser.post("/api/v1/auth/totp/enroll", headers={"Origin": "https://testserver"})
    assert no_csrf.status_code == 403


def test_accounts_do_not_share_authenticators(make_app: MakeApp, clock: FakeClock) -> None:
    app = make_app()
    one, two = Browser(app), Browser(app)
    one.login()
    two.login(phone=OTHER_PHONE)
    secret = enroll_and_confirm(one, clock)
    two.post("/api/v1/auth/totp/enroll")
    clock.advance(30)
    # Account one's code is not valid for account two.
    stolen = two.post("/api/v1/auth/totp/confirm", json={"code": code_for(secret, clock)})
    assert stolen.status_code == 422
    assert two.get("/api/v1/auth/me").json()["user"]["totpEnabled"] is False


def test_responses_and_audit_never_contain_secrets(
    browser: Browser, clock: FakeClock, db_url: str
) -> None:
    browser.login()
    secret = enroll_and_confirm(browser, clock)
    meta: Any = db_rows(db_url, "SELECT metadata_redacted::text AS m FROM audit_events")
    blob = " ".join(r["m"] for r in meta)
    assert secret not in blob and PHONE not in blob
    assert secret not in browser.get("/api/v1/auth/me").text


def test_unavailable_delivery_answers_every_number_the_same(
    make_app: MakeApp, provider: FixedOtpProvider
) -> None:
    """A reached cap must not reveal who is invited: invited and uninvited both get 503."""
    browser = Browser(make_app(otp_daily_delivery_limit=1))
    browser.get_csrf()
    assert browser.request_otp(PHONE).status_code == 202  # uses the day's one delivery
    invited = browser.request_otp(OTHER_PHONE)
    uninvited = browser.request_otp("+917654321098", invite=False)
    assert invited.status_code == uninvited.status_code == 503
    strip = {"requestId"}
    assert {k: v for k, v in invited.json().items() if k not in strip} == {
        k: v for k, v in uninvited.json().items() if k not in strip
    }


def test_disabled_provider_answers_every_number_with_503(make_app: MakeApp) -> None:
    from app.auth.otp import DisabledOtpProvider
    from app.main import create_app  # noqa: F401

    browser = Browser(make_app())
    browser.get_csrf()
    app = browser.client.app
    app.state.auth._provider = DisabledOtpProvider()  # type: ignore[attr-defined]
    invited = browser.request_otp(PHONE)
    uninvited = browser.request_otp(OTHER_PHONE, invite=False)
    assert invited.status_code == uninvited.status_code == 503
    strip = {"requestId"}
    assert {k: v for k, v in invited.json().items() if k not in strip} == {
        k: v for k, v in uninvited.json().items() if k not in strip
    }


def test_per_phone_cap_is_the_same_for_invited_and_uninvited_numbers(
    make_app: MakeApp, provider: FixedOtpProvider
) -> None:
    """The same request sequence gets the same statuses, so the cap reveals nothing."""

    def statuses(invited: bool) -> list[int]:
        browser = Browser(make_app(otp_daily_delivery_limit_per_phone=2))
        browser.get_csrf()
        phone = PHONE if invited else OTHER_PHONE
        return [browser.request_otp(phone, invite=invited).status_code for _ in range(4)]

    assert statuses(True) == statuses(False) == [202, 202, 503, 503]


def test_requests_rejected_by_the_phone_cap_do_not_spend_the_global_cap(
    make_app: MakeApp, provider: FixedOtpProvider
) -> None:
    browser = Browser(make_app(otp_daily_delivery_limit=3, otp_daily_delivery_limit_per_phone=1))
    browser.get_csrf()
    assert browser.request_otp(PHONE).status_code == 202
    assert browser.request_otp(PHONE).status_code == 503
    assert browser.request_otp(PHONE).status_code == 503
    # Only one code was sent, so two other numbers still fit under the global cap of 3.
    assert browser.request_otp(OTHER_PHONE).status_code == 202
    assert browser.request_otp("+917654321098").status_code == 202


def test_revoking_an_invite_ends_access_even_if_the_session_row_survives(
    browser: Browser, db_url: str
) -> None:
    browser.login()
    db_rows(db_url, "UPDATE invites SET revoked_at = now() WHERE phone_e164 = :p", p=PHONE)
    assert browser.get("/api/v1/auth/me").status_code == 401


def test_login_reports_an_existing_authenticator(make_app: MakeApp, clock: FakeClock) -> None:
    app = make_app()
    first = Browser(app)
    first.login()
    enroll_and_confirm(first, clock)
    second = Browser(app)
    response = second.login()
    assert response.json()["user"]["totpEnabled"] is True
    assert second.get("/api/v1/auth/me").json()["user"]["totpEnabled"] is True


def test_stored_step_up_window_never_passes_the_session_expiry(
    make_app: MakeApp, clock: FakeClock, db_url: str
) -> None:
    browser = Browser(make_app(session_absolute_ttl_seconds=300))
    browser.login()
    enroll_and_confirm(browser, clock)
    row = db_rows(db_url, "SELECT step_up_until, expires_at FROM sessions")[0]
    assert row["step_up_until"] == row["expires_at"]
    me = browser.get("/api/v1/auth/me").json()["session"]
    assert me["stepUpUntil"] is not None
