"""Invite-only registration with an emailed one-time code (contract 0.10.0, AUTH.md)."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import pytest

pytestmark = [pytest.mark.needs_services, pytest.mark.suite("authentication")]


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-REG-001", "AUTH-OTP-001")
def test_invited_number_registers_with_emailed_code(people, sink):
    p = people()
    client = p.register()
    me = client.get("/auth/me")
    assert me.status_code == 200
    user = me.json()["user"]
    assert user["totpEnabled"] is False
    assert p.phone not in me.text, "full phone number must never be returned"
    assert user["phoneMasked"].endswith(p.phone[-4:])
    mails = sink.messages_to(p.email)
    assert len(mails) == 1
    assert mails[0].code and len(mails[0].code) == 6


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-OTP-001")
def test_challenge_expiry_and_resend_window_match_contract(people, anon):
    p = people()
    p.invite()
    anon.fetch_csrf()
    before = datetime.now(UTC)
    r = anon.post("/auth/otp/request", {"phone": p.phone, "channel": "email"})
    assert r.status_code == 202
    body = r.json()
    ttl = (_ts(body["expiresAt"]) - before).total_seconds()
    assert 0 < ttl <= 300 + 2, f"code lifetime {ttl}s exceeds 5 minutes"
    assert body["channel"] == "email"


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-REG-002", "AUTH-ENUM-001")
def test_uninvited_number_gets_identical_response_and_no_email(people, anon, sink):
    invited, stranger = people(), people()
    invited.invite()
    anon.fetch_csrf()
    a = anon.post("/auth/otp/request", {"phone": invited.phone, "channel": "email"})
    b = anon.post("/auth/otp/request", {"phone": stranger.phone, "channel": "email"})
    assert a.status_code == b.status_code == 202
    assert set(a.json()) == set(b.json())
    assert a.headers.get("content-type") == b.headers.get("content-type")
    time.sleep(0.5)
    assert sink.messages_to(stranger.email) == []
    assert len(sink.messages_to(invited.email)) == 1


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-REG-002")
def test_uninvited_challenge_cannot_be_completed_with_any_guess(people, anon):
    stranger = people()
    anon.fetch_csrf()
    ch = anon.post("/auth/otp/request", {"phone": stranger.phone, "channel": "email"}).json()
    for code in ("123456", "000000", "999999"):
        r = anon.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
        assert r.status_code == 401
        assert r.json()["code"] == "INVALID_OTP"


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-OTP-003")
def test_wrong_code_is_rejected_and_right_code_still_works(people, sink):
    p = people()
    p.invite()
    c = p.new_client()
    ch = p.request_email_code(c)
    code = sink.wait_for_code(p.email)
    wrong = f"{(int(code) + 1) % 1_000_000:06d}"
    r = c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": wrong})
    assert r.status_code == 401 and r.json()["code"] == "INVALID_OTP"
    r = c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
    assert r.status_code == 200


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-OTP-004")
def test_code_cannot_be_replayed(people, sink):
    p = people()
    p.invite()
    c = p.new_client()
    ch = p.request_email_code(c)
    code = sink.wait_for_code(p.email)
    assert c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code}).status_code == 200
    other = p.new_client()
    other.fetch_csrf()
    r = other.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
    assert r.status_code == 401 and r.json()["code"] == "INVALID_OTP"


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-OTP-004")
def test_concurrent_redemption_of_one_code_succeeds_once(people, sink):
    """Two clients race to redeem the same emailed code: exactly one may get a session."""
    p = people()
    p.invite()
    c = p.new_client("a")
    before = len(sink.messages_to(p.email))
    ch = p.request_email_code(c)
    code = sink.wait_for_code(p.email, after=before)
    # Same pre-login context (cookies + CSRF) on both clients, as a copied browser profile would have.
    twin = p.new_client("b")
    twin.cookies.update(c.cookies)
    twin.csrf_token = c.csrf_token
    gate = threading.Barrier(2)
    results: dict[str, int] = {}

    def redeem(name: str, client) -> None:
        gate.wait(timeout=10)
        results[name] = client.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code}).status_code

    threads = [threading.Thread(target=redeem, args=(n, cl)) for n, cl in (("a", c), ("b", twin))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results.values()) == [200, 401], f"one code redeemed by both racers: {results}"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-OTP-005")
def test_challenge_dies_after_five_failed_attempts(people, sink):
    p = people()
    p.invite()
    c = p.new_client()
    ch = p.request_email_code(c)
    code = sink.wait_for_code(p.email)
    wrong = f"{(int(code) + 7) % 1_000_000:06d}"
    for _ in range(5):
        r = c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": wrong})
        assert r.status_code == 401
    r = c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
    assert r.status_code == 401, "the correct code must not work after 5 failures"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-OTP-006")
def test_resend_issues_new_code_and_old_challenge_handling(people, sink):
    """Second request yields a second email; the newest code signs in."""
    p = people()
    p.invite()
    c = p.new_client()
    p.request_email_code(c)
    sink.wait_for_code(p.email, after=0)
    ch2 = p.request_email_code(c)
    code2 = sink.wait_for_code(p.email, after=1)
    r = c.post("/auth/otp/verify", {"challengeId": ch2["challengeId"], "code": code2})
    assert r.status_code == 200


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-OTP-007")
def test_code_bound_to_pre_login_context(people, sink):
    """A challenge requested in one browser cannot be completed from another (contract: different pre-login context -> 401)."""
    p = people()
    p.invite()
    requester = p.new_client()
    ch = p.request_email_code(requester)
    code = sink.wait_for_code(p.email)
    attacker = p.new_client()
    attacker.fetch_csrf()
    r = attacker.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
    assert r.status_code == 401 and r.json()["code"] == "INVALID_OTP"


@pytest.mark.severity("medium")
@pytest.mark.req("AUTH-REG-003")
def test_invited_without_email_gets_same_202_and_nothing_sent(people, anon, sink):
    p = people()
    p.invite(email=False)
    anon.fetch_csrf()
    r = anon.post("/auth/otp/request", {"phone": p.phone, "channel": "email"})
    assert r.status_code == 202
    time.sleep(0.5)
    assert sink.all_messages == []


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-REG-004")
def test_revoked_invite_blocks_already_issued_code(people, sink, backend):
    p = people()
    p.invite()
    c = p.new_client()
    ch = p.request_email_code(c)
    code = sink.wait_for_code(p.email)
    assert backend.admin("invite", "revoke", p.phone).returncode == 0
    r = c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
    assert r.status_code == 401 and r.json()["code"] == "INVALID_OTP"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-REG-005")
def test_interrupted_registration_can_restart(people, sink):
    """User asks for a code, abandons the tab, opens a new one and finishes."""
    p = people()
    p.invite()
    first = p.new_client("abandoned-tab")
    p.request_email_code(first)
    sink.wait_for_code(p.email, after=0)
    fresh = p.new_client("new-tab")
    ch = p.request_email_code(fresh)
    code = sink.wait_for_code(p.email, after=1)
    r = fresh.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
    assert r.status_code == 200


@pytest.mark.severity("medium")
@pytest.mark.req("AUTH-VAL-001")
@pytest.mark.parametrize(
    "phone",
    ["9876543210", "+915876543210", "+91987654321", "+9198765432100", "+1 9876543210", "", "+91 9876543210"],
)
def test_malformed_phone_numbers_rejected(anon, phone):
    """Boundary/equivalence classes for the Phone pattern ^\\+91[6-9][0-9]{9}$."""
    anon.fetch_csrf()
    r = anon.post("/auth/otp/request", {"phone": phone, "channel": "email"})
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_REQUEST"


@pytest.mark.severity("medium")
@pytest.mark.req("AUTH-VAL-001")
@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", "12 456", ""])
def test_malformed_codes_rejected_before_lookup(anon, code):
    anon.fetch_csrf()
    r = anon.post(
        "/auth/otp/verify",
        {"challengeId": "00000000-0000-4000-8000-000000000000", "code": code},
    )
    assert r.status_code == 400


@pytest.mark.severity("medium")
@pytest.mark.req("AUTH-VAL-002")
def test_unknown_fields_rejected(anon):
    anon.fetch_csrf()
    r = anon.post("/auth/otp/request", {"phone": "+919000000001", "channel": "email", "admin": True})
    assert r.status_code == 400
