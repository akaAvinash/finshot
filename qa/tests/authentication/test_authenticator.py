"""Authenticator (TOTP) enrolment, sign-in, drift, replay, step-up and recovery codes."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from urllib.parse import unquote

import pytest

from qa.core.totp import STEP_SECONDS, TotpDevice, parse_otpauth, step_at

pytestmark = [pytest.mark.needs_services, pytest.mark.suite("authentication")]


def _wrong(code: str) -> str:
    return f"{(int(code) + 500_001) % 1_000_000:06d}"


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-TOTP-001", "AUTH-TOTP-002")
def test_enrolment_returns_valid_secret_and_qr_uri(people):
    p = people()
    c = p.register()
    r = c.post("/auth/totp/enroll")
    assert r.status_code == 200
    e = r.json()
    assert re.fullmatch(r"[A-Z2-7]{32}", e["secret"]), "160-bit base32 secret"
    uri = parse_otpauth(e["otpauthUri"])
    assert uri.secret == e["secret"], "QR URI must carry the same secret as the manual-entry text"
    assert (uri.algorithm, uri.digits, uri.period) == ("SHA1", 6, 30)
    for where, text in (("URI", e["otpauthUri"]), ("decoded URI", unquote(e["otpauthUri"])), ("label", uri.label)):
        assert p.phone not in text and p.phone.lstrip("+") not in text, f"QR {where} exposes the full phone number"
    # Manual setup: a device built from the text secret alone can confirm.
    dev = TotpDevice(e["secret"])
    code, _ = dev.fresh_code()
    r = c.post("/auth/totp/confirm", {"code": code})
    assert r.status_code == 200
    assert r.json()["totpEnabled"] is True
    assert c.get("/auth/me").json()["user"]["totpEnabled"] is True


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-TOTP-003")
def test_confirm_with_wrong_code_does_not_activate(people):
    p = people()
    c = p.register()
    e = c.post("/auth/totp/enroll").json()
    code, _ = TotpDevice(e["secret"]).fresh_code()
    r = c.post("/auth/totp/confirm", {"code": _wrong(code)})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_TOTP"
    assert c.get("/auth/me").json()["user"]["totpEnabled"] is False


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-TOTP-004")
def test_second_enrolment_refused_when_active(people):
    p = people()
    c = p.register_ready()
    r = c.post("/auth/totp/enroll")
    assert r.status_code == 409 and r.json()["code"] == "TOTP_ALREADY_ENROLLED"


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-TOTP-005")
def test_phone_and_totp_sign_in(people):
    p = people()
    p.register_ready()
    c = p.login_totp()
    me = c.get("/auth/me").json()
    assert me["user"]["totpEnabled"] is True
    assert me["session"]["stepUpUntil"] is not None, "TOTP sign-in opens the step-up window"


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-TOTP-006")
def test_totp_code_cannot_be_replayed(people):
    p = people()
    p.register_ready()
    first = p.new_client()
    first.fetch_csrf()
    code, step = p.device.fresh_code()
    assert first.post("/auth/login/totp", {"phone": p.phone, "code": code}).status_code == 200
    p.device.mark_used(step)
    second = p.new_client()
    second.fetch_csrf()
    r = second.post("/auth/login/totp", {"phone": p.phone, "code": code})
    assert r.status_code == 401 and r.json()["code"] == "INVALID_CREDENTIALS"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-TOTP-007")
def test_clock_drift_one_step_accepted_two_steps_rejected(people):
    """Server allows +/-1 step. Codes 2 steps away must fail; 1 step behind must work."""
    p = people()
    p.register_ready()
    dev = p.device
    # Wait until we're safely inside a step that is newer than the confirm step + 2.
    while True:
        now = time.time()
        if step_at(now) - 1 > dev.last_used_step and (STEP_SECONDS - now % STEP_SECONDS) > 4:
            break
        time.sleep(1)
    now_step = step_at(time.time())
    c = p.new_client()
    c.fetch_csrf()
    for far in (now_step - 2, now_step + 2):
        r = c.post("/auth/login/totp", {"phone": p.phone, "code": dev.code_for_step(far)})
        assert r.status_code == 401, f"step offset {far - now_step} must be rejected"
    r = c.post("/auth/login/totp", {"phone": p.phone, "code": dev.code_for_step(now_step - 1)})
    assert r.status_code == 200, "one step of drift must be accepted"


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-TOTP-008", "AUTH-ENUM-002")
def test_totp_login_failures_are_uniform(people):
    """Wrong code, unknown number, uninvited and no-authenticator all look identical."""
    ready, no_totp, stranger = people(), people(), people()
    ready.register_ready()
    no_totp.register()
    c = ready.new_client()
    c.fetch_csrf()
    code, _ = ready.device.fresh_code()
    bodies = []
    for phone, attempt in (
        (ready.phone, _wrong(code)),
        (no_totp.phone, code),
        (stranger.phone, code),
    ):
        r = c.post("/auth/login/totp", {"phone": phone, "code": attempt})
        assert r.status_code == 401
        body = r.json()
        body.pop("requestId", None)
        bodies.append(body)
    assert bodies[0] == bodies[1] == bodies[2]
    assert bodies[0]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-TOTP-009")
def test_email_code_cannot_start_session_once_authenticator_active(people, sink):
    p = people()
    registered = p.register()
    # A real, unused emailed code issued before the authenticator is activated...
    pending = p.new_client("pending")
    before = len(sink.messages_to(p.email))
    early = p.request_email_code(pending)
    early_code = sink.wait_for_code(p.email, after=before)
    p.enroll(registered)
    # ...must not start a session once the authenticator is active.
    r = pending.post("/auth/otp/verify", {"challengeId": early["challengeId"], "code": early_code})
    assert r.status_code == 401, f"pre-activation email code still signs in: {r.status_code}"
    assert pending.get("/auth/me").status_code == 401
    # And no new email code is sent after activation.
    c = p.new_client()
    before = len(sink.messages_to(p.email))
    ch = p.request_email_code(c)
    time.sleep(0.5)
    assert len(sink.messages_to(p.email)) == before, "nothing is sent once an authenticator is active"
    r = c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": early_code})
    assert r.status_code == 401


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-TOTP-010")
def test_totp_login_rate_limited_per_phone(people):
    p = people()
    p.register_ready()
    c = p.new_client()
    c.fetch_csrf()
    code, _ = p.device.fresh_code()
    statuses = [c.post("/auth/login/totp", {"phone": p.phone, "code": _wrong(code)}).status_code for _ in range(6)]
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429
    r = c.post("/auth/login/totp", {"phone": p.phone, "code": _wrong(code)})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert r.json()["retryAfterSeconds"] == int(r.headers["Retry-After"])


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-STEP-001")
def test_step_up_wrong_code_does_not_open_window(people):
    p = people()
    c = p.register_ready()
    # A fresh registration session; close the window by signing in fresh is not possible,
    # so use a login session and check step-up rejection semantics on the wrong code.
    code, _ = p.device.fresh_code()
    before = c.get("/auth/me").json()["session"]["stepUpUntil"]
    r = c.post("/auth/step-up", {"code": _wrong(code)})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_TOTP"
    assert c.get("/auth/me").json()["session"]["stepUpUntil"] == before, "a wrong code must not move the window"
    # The closed-window case needs a 60 s wait: see test_expiry_slow::test_step_up_window_closes.


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-STEP-002")
def test_disable_requires_valid_code_and_closes_windows(people):
    p = people()
    c = p.register_ready()
    other = p.login_totp()
    code, _ = p.device.fresh_code()
    assert c.post("/auth/totp/disable", {"code": _wrong(code)}).status_code == 422
    code, step = p.device.fresh_code()
    r = c.post("/auth/totp/disable", {"code": code})
    assert r.status_code == 204
    p.device.mark_used(step)
    me = other.get("/auth/me").json()
    assert me["user"]["totpEnabled"] is False
    assert me["session"]["stepUpUntil"] is None, "disable must close the window on every session"


# ------------------------------------------------------------ recovery codes --
@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-REC-001")
def test_recovery_codes_generated_once_ten_unique(people):
    p = people()
    c = p.register_ready()
    codes = p.create_recovery_codes(c)
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(re.fullmatch(r"[A-Z2-7]{5}-[A-Z2-7]{5}", x) for x in codes)


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-REC-002", "AUTH-REC-003")
def test_recovery_code_single_use_and_resets_authenticator(people):
    p = people()
    c = p.register_ready()
    codes = p.create_recovery_codes(c)
    rec = p.new_client("lost-phone")
    rec.fetch_csrf()
    r = rec.post("/auth/login/recovery", {"phone": p.phone, "recoveryCode": codes[0]})
    assert r.status_code == 200
    body = rec.adopt_login(r)
    assert body["user"]["totpEnabled"] is False
    assert body["session"]["stepUpUntil"] is None
    # Replay of the same code
    again = p.new_client()
    again.fetch_csrf()
    r = again.post("/auth/login/recovery", {"phone": p.phone, "recoveryCode": codes[0]})
    assert r.status_code == 401 and r.json()["code"] == "INVALID_CREDENTIALS"
    # Every other code died with the authenticator
    r = again.post("/auth/login/recovery", {"phone": p.phone, "recoveryCode": codes[1]})
    assert r.status_code == 401
    # Lost-authenticator recovery: the recovered session can enrol a new authenticator now.
    p.enroll(rec)
    assert rec.get("/auth/me").json()["user"]["totpEnabled"] is True


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-REC-004")
def test_regenerating_codes_invalidates_old_set(people):
    p = people()
    c = p.register_ready()
    old = p.create_recovery_codes(c)
    p.create_recovery_codes(c)
    x = p.new_client()
    x.fetch_csrf()
    r = x.post("/auth/login/recovery", {"phone": p.phone, "recoveryCode": old[0]})
    assert r.status_code == 401


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-REC-005")
def test_recovery_code_of_one_account_does_not_work_for_another(people):
    a, b = people(), people()
    ca = a.register_ready()
    b.register_ready()
    codes = a.create_recovery_codes(ca)
    x = b.new_client()
    x.fetch_csrf()
    r = x.post("/auth/login/recovery", {"phone": b.phone, "recoveryCode": codes[0]})
    assert r.status_code == 401


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-REC-006")
def test_operator_totp_reset_then_reregister(people, backend, sink):
    p = people()
    p.register_ready()
    assert backend.admin("totp-reset", p.phone).returncode == 0
    c = p.new_client()
    before = len(sink.messages_to(p.email))
    ch = p.request_email_code(c)
    code = sink.wait_for_code(p.email, after=before)
    r = c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
    assert r.status_code == 200
    assert r.json()["user"]["totpEnabled"] is False


@pytest.mark.severity("medium")
@pytest.mark.req("AUTH-STEP-003")
def test_step_up_window_bounded_by_session_expiry(people):
    p = people()
    p.register_ready()
    c = p.login_totp()
    s = c.get("/auth/me").json()["session"]
    until = datetime.fromisoformat(s["stepUpUntil"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(s["expiresAt"].replace("Z", "+00:00"))
    assert until <= expires
    assert (until - datetime.now(UTC)).total_seconds() <= 600 + 5, "window is at most 10 minutes"
