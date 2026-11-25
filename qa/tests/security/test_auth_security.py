"""Security checks on the auth surface: secret leakage, headers, throttling, delivery caps."""

from __future__ import annotations

import re
import time

import pytest

from qa.core.actors import Person
from qa.core.client import ApiClient

pytestmark = [pytest.mark.needs_services, pytest.mark.suite("security")]


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("SEC-LEAK-001", "SEC-LEAK-002")
def test_no_codes_secrets_or_pii_in_server_logs(backend_factory, sink):
    """Drive a full account lifecycle on a private backend, then scan its entire log output."""
    b = backend_factory("leak-scan", OTP_RESEND_COOLDOWN_SECONDS="0", LOG_LEVEL="DEBUG")
    p = Person(b, sink)
    c = p.register_ready()
    codes = p.create_recovery_codes(c)
    other = p.login_totp()
    secret = p.device.secret
    emailed = [m.code for m in sink.messages_to(p.email) if m.code]
    rec = ApiClient(b.base_url, name="rec")
    rec.fetch_csrf()
    assert rec.post("/auth/login/recovery", {"phone": p.phone, "recoveryCode": codes[0]}).status_code == 200
    csrf_tokens = [x for x in (c.csrf_token, other.csrf_token, rec.csrf_token) if x]
    session_ids = [cl.cookies.get("__Host-tradeo_session") for cl in (c, other, rec)]
    time.sleep(0.5)
    b.stop()  # flush
    logs = b.logs()
    assert '"event"' in logs and "login" in logs, "positive control: the scanned log must contain auth events"
    leaks = []
    for label, values in (
        ("phone", [p.phone, p.phone.lstrip("+")]),
        ("email", [p.email]),
        ("totp secret", [secret]),
        ("recovery code", codes),
        # Emailed OTPs are six digits and would match unrelated numbers as substrings;
        # they are checked below as standalone tokens only.
        ("csrf token", csrf_tokens),
        ("session cookie", [s for s in session_ids if s]),
        ("smtp password", [sink.password]),
    ):
        for v in values:
            if v and v in logs:
                leaks.append(label)
                break
    # Emailed and submitted TOTP codes are six digits; flag them only as standalone tokens.
    assert p.submitted_totp, "positive control: the lifecycle submitted TOTP codes"
    for label, codes_ in (("emailed OTP", emailed), ("submitted TOTP code", p.submitted_totp)):
        for code in codes_:
            if re.search(rf"(?<!\d){re.escape(code)}(?!\d)", logs) and label not in leaks:
                leaks.append(label)
    assert not leaks, f"sensitive values found in server logs: {sorted(set(leaks))}"


@pytest.mark.severity("high")
@pytest.mark.req("SEC-HDR-002")
def test_security_headers_on_auth_responses(anon):
    r = anon.get("/auth/csrf")
    h = {k.lower(): v for k, v in r.headers.items()}
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options", "").upper() == "DENY" or "frame-ancestors" in h.get("content-security-policy", "")
    assert "no-store" in h.get("cache-control", "")
    assert h.get("referrer-policy")
    assert "x-request-id" in h


@pytest.mark.severity("high")
@pytest.mark.req("SEC-LEAK-003")
def test_api_responses_never_echo_codes(people, sink):
    p = people()
    p.invite()
    c = p.new_client()
    ch = p.request_email_code(c)
    code = sink.wait_for_code(p.email)
    assert code not in str(ch)
    r = c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
    assert code not in r.text


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-RATE-001")
def test_otp_requests_throttled_per_phone(backend_factory, sink):
    """Default: 5 OTP requests per phone per hour. The per-context and per-IP limits are
    raised on this private backend so the 429 can only come from the per-phone limit."""
    b = backend_factory(
        "otp-phone-limit",
        OTP_RESEND_COOLDOWN_SECONDS="0",
        RATE_LIMIT_OTP_REQUEST_PER_CONTEXT="50",
        RATE_LIMIT_OTP_REQUEST_PER_IP="50",
    )
    p = Person(b, sink)
    p.invite()
    c = p.new_client()
    c.fetch_csrf()
    statuses = [c.post("/auth/otp/request", {"phone": p.phone, "channel": "email"}).status_code for _ in range(6)]
    assert statuses == [202] * 5 + [429], statuses


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-ENUM-003")
def test_throttle_is_identical_for_invited_and_uninvited(people, anon):
    invited, stranger = people(), people()
    invited.invite()
    anon.fetch_csrf()
    a = [anon.post("/auth/otp/request", {"phone": invited.phone, "channel": "email"}).status_code for _ in range(6)]
    anon.cookies.clear()
    anon.fetch_csrf()
    b = [anon.post("/auth/otp/request", {"phone": stranger.phone, "channel": "email"}).status_code for _ in range(6)]
    assert a == b, f"throttle differs (reveals invite status): invited={a} uninvited={b}"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-OTP-006", "AUTH-RATE-003")
def test_resend_cooldown_enforced(backend_factory, sink):
    b = backend_factory("cooldown", OTP_RESEND_COOLDOWN_SECONDS="60")
    p = Person(b, sink)
    p.invite()
    c = p.new_client()
    first = p.request_email_code(c)
    r = c.post("/auth/otp/request", {"phone": p.phone, "channel": "email"})
    assert r.status_code == 429, f"second request inside the 60 s cooldown must be refused, got {r.status_code}"
    assert int(r.headers.get("Retry-After", "0")) >= 1
    assert len(sink.messages_to(p.email)) == 1
    from datetime import datetime

    def ts(v: str) -> datetime:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))

    # Both are set from the same creation time: expiry +300 s, resend +60 s.
    gap = (ts(first["expiresAt"]) - ts(first["resendAvailableAt"])).total_seconds()
    assert 235 <= gap <= 245, f"resend window is not 60 s inside a 300 s code lifetime (gap {gap})"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-CAP-001", "AUTH-ENUM-004")
def test_daily_delivery_cap_fails_uniformly(backend_factory, sink):
    b = backend_factory("daily-cap", OTP_RESEND_COOLDOWN_SECONDS="0", OTP_DAILY_DELIVERY_LIMIT="2")
    a1, a2, a3, stranger = (Person(b, sink) for _ in range(4))
    for x in (a1, a2, a3):
        x.invite()
    c = ApiClient(b.base_url, name="cap")
    c.fetch_csrf()
    s1 = c.post("/auth/otp/request", {"phone": a1.phone, "channel": "email"}).status_code
    s2 = c.post("/auth/otp/request", {"phone": a2.phone, "channel": "email"}).status_code
    r3 = c.post("/auth/otp/request", {"phone": a3.phone, "channel": "email"})
    r4 = c.post("/auth/otp/request", {"phone": stranger.phone, "channel": "email"})
    assert (s1, s2) == (202, 202)
    assert r3.status_code == r4.status_code == 503
    assert r3.json()["code"] == r4.json()["code"] == "OTP_DELIVERY_UNAVAILABLE"
    assert sink.messages_to(a3.email) == []


@pytest.mark.severity("medium")
@pytest.mark.req("SEC-HOST-001")
def test_unknown_host_header_rejected(backend):
    import httpx

    r = httpx.get(f"{backend.base_url}/api/v1/auth/csrf", headers={"Host": "evil.example"})
    assert r.status_code == 400


@pytest.mark.severity("medium")
@pytest.mark.req("SEC-INPUT-001")
@pytest.mark.parametrize(
    "payload",
    [
        {"phone": "+919876543210' OR '1'='1", "channel": "email"},
        {"phone": "+919876543210", "channel": "email\u0000"},
        {"phone": ["+919876543210"], "channel": "email"},
        {"phone": "+91" + "9" * 5000, "channel": "email"},
    ],
)
def test_hostile_input_rejected_cleanly(anon, payload):
    anon.fetch_csrf()
    r = anon.post("/auth/otp/request", payload)
    assert r.status_code == 400
    assert "Traceback" not in r.text and "sqlalchemy" not in r.text.lower()


@pytest.mark.severity("medium")
@pytest.mark.req("SEC-LEAK-004")
def test_operator_invite_list_masks_numbers(people, backend):
    """AUTH.md documents `invite list` as masked output."""
    p = people()
    p.invite()
    out = backend.admin("invite", "list")
    assert out.returncode == 0
    assert p.phone not in out.stdout, "invite list prints full phone numbers (AUTH.md says masked)"
    assert p.email not in out.stdout, "invite list prints full email addresses"
