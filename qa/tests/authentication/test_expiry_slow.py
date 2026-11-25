"""Expiry windows checked against the real clock (nightly: these wait 30-70 s each).

Each test runs a private backend with the shortest TTL the settings allow, so
the behaviour is the production code path with a shorter number.
"""

from __future__ import annotations

import time

import pytest

from qa.core.actors import Person

pytestmark = [pytest.mark.needs_services, pytest.mark.slow, pytest.mark.suite("authentication")]


@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-OTP-002")
def test_emailed_code_expires(backend_factory, sink):
    b = backend_factory("otp-ttl", OTP_TTL_SECONDS="30", OTP_RESEND_COOLDOWN_SECONDS="0")
    p = Person(b, sink)
    p.invite()
    c = p.new_client()
    ch = p.request_email_code(c)
    code = sink.wait_for_code(p.email)
    time.sleep(32)
    r = c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
    assert r.status_code == 401 and r.json()["code"] == "INVALID_OTP"


@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-SESS-010")
def test_idle_session_expires(backend_factory, sink):
    b = backend_factory("idle-ttl", SESSION_IDLE_TTL_SECONDS="60", OTP_RESEND_COOLDOWN_SECONDS="0")
    p = Person(b, sink)
    c = p.register_ready()
    assert c.get("/auth/me").status_code == 200
    time.sleep(63)
    assert c.get("/auth/me").status_code == 401


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-SESS-011")
def test_activity_extends_idle_expiry(backend_factory, sink):
    b = backend_factory("idle-extend", SESSION_IDLE_TTL_SECONDS="60", OTP_RESEND_COOLDOWN_SECONDS="0")
    p = Person(b, sink)
    c = p.register_ready()
    for _ in range(3):
        time.sleep(35)
        assert c.get("/auth/me").status_code == 200, "activity inside the idle window keeps the session"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-STEP-004")
def test_step_up_window_closes(backend_factory, sink):
    b = backend_factory("stepup-ttl", STEP_UP_TTL_SECONDS="60", OTP_RESEND_COOLDOWN_SECONDS="0")
    p = Person(b, sink)
    c = p.register_ready()
    p.login_totp()
    time.sleep(63)
    target = next(s for s in c.get("/auth/sessions").json()["sessions"] if not s["current"])
    r = c.delete(f"/auth/sessions/{target['id']}")
    assert r.status_code == 403 and r.json()["code"] == "STEP_UP_REQUIRED"
    # A wrong code on a closed window must not open it.
    good, _ = p.device.fresh_code()
    wrong = f"{(int(good) + 1) % 1_000_000:06d}"
    r = c.post("/auth/step-up", {"code": wrong})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_TOTP"
    r = c.delete(f"/auth/sessions/{target['id']}")
    assert r.status_code == 403 and r.json()["code"] == "STEP_UP_REQUIRED", "wrong code opened the window"
