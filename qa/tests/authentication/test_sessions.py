"""Sessions, logout, revocation, concurrency, CSRF, cookies and account isolation."""

from __future__ import annotations

import concurrent.futures as cf

import pytest

from qa.core.client import CSRF_COOKIE, SESSION_COOKIE

pytestmark = [pytest.mark.needs_services, pytest.mark.suite("authentication")]


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-SESS-001")
def test_unauthenticated_requests_are_rejected(anon):
    for path in ("/auth/me", "/auth/sessions", "/settings/profile", "/alerts", "/reports/paper"):
        r = anon.get(path)
        assert r.status_code == 401, path
        assert r.json()["code"] == "UNAUTHENTICATED"


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-SESS-002")
def test_logout_ends_session_server_side(people):
    p = people()
    c = p.register_ready()
    stolen = dict(c.cookies)
    r = c.post("/auth/logout")
    assert r.status_code == 204
    assert {x.name for x in c.last_set_cookies if x.cleared} == {SESSION_COOKIE, CSRF_COOKIE}
    replay = p.new_client("replayed-cookie")
    replay.cookies.update(stolen)
    assert replay.get("/auth/me").status_code == 401, "a captured cookie must die with logout"


@pytest.mark.severity("medium")
@pytest.mark.req("AUTH-SESS-002")
def test_logout_is_idempotent(people):
    p = people()
    c = p.register_ready()
    assert c.post("/auth/logout").status_code == 204
    c.fetch_csrf()
    assert c.post("/auth/logout").status_code == 204


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-SESS-003")
def test_logout_all_ends_every_device(people):
    p = people()
    laptop = p.register_ready()
    phone = p.login_totp()
    tablet = p.login_totp()
    assert laptop.post("/auth/logout-all").status_code == 204
    for c in (laptop, phone, tablet):
        c.cookies.pop(CSRF_COOKIE, None)
    assert phone.get("/auth/me").status_code == 401
    assert tablet.get("/auth/me").status_code == 401


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-SESS-004")
def test_revoke_other_session_with_step_up(people):
    p = people()
    main = p.register_ready()  # confirm opened the step-up window
    other = p.login_totp()
    sessions = main.get("/auth/sessions").json()["sessions"]
    assert len(sessions) >= 2
    assert sum(s["current"] for s in sessions) == 1
    target = next(s for s in sessions if not s["current"])
    r = main.delete(f"/auth/sessions/{target['id']}")
    assert r.status_code == 204
    # Which one did we end? Exactly one of the remaining clients stays signed in.
    remaining = [c.get("/auth/me").status_code for c in (main, other)]
    assert remaining[0] == 200
    assert main.delete(f"/auth/sessions/{target['id']}").status_code == 404, "repeat answers 404"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-SESS-005")
def test_cannot_revoke_own_session_or_probe_foreign_ids(people):
    a, b = people(), people()
    ca = a.register_ready()
    cb = b.register_ready()
    own = next(s for s in ca.get("/auth/sessions").json()["sessions"] if s["current"])
    assert ca.delete(f"/auth/sessions/{own['id']}").status_code == 409
    foreign = cb.get("/auth/sessions").json()["sessions"][0]["id"]
    r = ca.delete(f"/auth/sessions/{foreign}")
    assert r.status_code == 404, "another user's session must look like it does not exist"
    assert cb.get("/auth/me").status_code == 200


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-ISO-001")
def test_session_list_only_shows_own_sessions(people):
    a, b = people(), people()
    ca = a.register_ready()
    cb = b.register_ready()
    ids_a = {s["id"] for s in ca.get("/auth/sessions").json()["sessions"]}
    ids_b = {s["id"] for s in cb.get("/auth/sessions").json()["sessions"]}
    assert ids_a and ids_b and not (ids_a & ids_b)


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-ISO-002")
def test_profile_isolated_between_accounts(people):
    a, b = people(), people()
    ca = a.register_ready()
    cb = b.register_ready()
    r = ca.put("/settings/profile", {"displayName": "QA Alpha", "timezone": "Asia/Kolkata"})
    assert r.status_code == 200, r.text
    assert cb.get("/settings/profile").json()["displayName"] != "QA Alpha"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-SESS-006")
def test_concurrent_sessions_are_independent(people):
    p = people()
    first = p.register_ready()
    second = p.login_totp()
    assert first.post("/auth/logout").status_code == 204
    assert second.get("/auth/me").status_code == 200


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-SETUP-001")
def test_session_without_authenticator_is_limited_to_setup(people):
    p = people()
    c = p.register()
    assert c.get("/auth/me").status_code == 200
    r = c.get("/auth/sessions")
    assert r.status_code == 403 and r.json()["code"] == "TOTP_SETUP_REQUIRED"
    r = c.get("/settings/profile")
    assert r.status_code == 403 and r.json()["code"] == "TOTP_SETUP_REQUIRED"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-SESS-007")
def test_csrf_refresh_after_revoked_session_returns_pre_login(people):
    """Browser refresh after the session was ended elsewhere: the app recovers to signed-out."""
    p = people()
    a = p.register_ready()
    b = p.login_totp()
    assert a.post("/auth/logout-all").status_code == 204
    data = b.fetch_csrf()
    assert data["context"] == "pre_login"
    assert any(x.name == SESSION_COOKIE and x.cleared for x in b.last_set_cookies)
    assert SESSION_COOKIE not in b.cookies


@pytest.mark.severity("medium")
@pytest.mark.req("AUTH-SESS-008")
def test_browser_refresh_keeps_session(people):
    """Refresh = new CSRF fetch with existing cookie; session context is kept."""
    p = people()
    c = p.register_ready()
    data = c.fetch_csrf()
    assert data["context"] == "session"
    assert c.get("/auth/me").status_code == 200


# --------------------------------------------------------------------- CSRF --
@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-CSRF-001")
@pytest.mark.parametrize("variant", ["missing", "garbage", "pre_login_token"])
def test_session_writes_require_session_csrf(people, variant):
    p = people()
    c = p.register_ready()
    if variant == "missing":
        r = c.post("/auth/logout-all", csrf=False)
    elif variant == "garbage":
        r = c.post("/auth/logout-all", csrf="x" * 40)
    else:
        outsider = p.new_client()
        token = outsider.fetch_csrf()["csrfToken"]
        r = c.post("/auth/logout-all", csrf=token)
    assert r.status_code == 403 and r.json()["code"] == "CSRF_FAILED"
    assert c.get("/auth/me").status_code == 200, "nothing changed"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-CSRF-002")
def test_pre_login_writes_require_csrf(anon):
    r = anon.post("/auth/otp/request", {"phone": "+919000000002", "channel": "email"})
    assert r.status_code == 403 and r.json()["code"] == "CSRF_FAILED"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-CSRF-003")
def test_csrf_header_must_match_cookie(people):
    p = people()
    c = p.register_ready()
    other = p.login_totp()
    r = c.post("/auth/logout-all", csrf=other.csrf_token)
    assert r.status_code == 403


# ------------------------------------------------------------------ cookies --
@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-COOKIE-001")
def test_login_cookies_have_secure_attributes(people, sink):
    p = people()
    p.invite()
    c = p.new_client()
    ch = p.request_email_code(c)
    code = sink.wait_for_code(p.email)
    r = c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
    assert r.status_code == 200
    set_cookies = c.last_set_cookies
    assert [x.name for x in set_cookies] == [SESSION_COOKIE, CSRF_COOKIE], "two fields, session then CSRF"
    for ck in set_cookies:
        assert ck.attrs.get("secure") == "true", ck.name
        assert ck.attrs.get("httponly") == "true", ck.name
        assert ck.attrs.get("samesite", "").lower() in ("lax", "strict"), ck.name
        assert ck.attrs.get("path") == "/", ck.name
        assert "domain" not in ck.attrs, f"{ck.name}: __Host- cookies must not set Domain"


@pytest.mark.critical_gate
@pytest.mark.severity("critical")
@pytest.mark.req("AUTH-COOKIE-002")
def test_session_id_rotates_on_login(people):
    """Session fixation: a pre-set session cookie is not adopted."""
    p = people()
    p.invite()
    c = p.new_client()
    c.cookies[SESSION_COOKIE] = "attacker-chosen-value-0000000000000000"
    c.fetch_csrf()
    ch = p.request_email_code(c)
    code = p.sink.wait_for_code(p.email)
    r = c.post("/auth/otp/verify", {"challengeId": ch["challengeId"], "code": code})
    assert r.status_code == 200
    assert c.cookies[SESSION_COOKIE] != "attacker-chosen-value-0000000000000000"


@pytest.mark.severity("high")
@pytest.mark.req("AUTH-SESS-009")
def test_parallel_logins_create_distinct_sessions(people):
    p = people()
    p.register_ready()
    clients = [p.new_client(f"par{i}") for i in range(3)]
    for c in clients:
        c.fetch_csrf()
    code, step = p.device.fresh_code()

    def attempt(c):
        return c.post("/auth/login/totp", {"phone": p.phone, "code": code}).status_code

    with cf.ThreadPoolExecutor(3) as pool:
        statuses = list(pool.map(attempt, clients))
    p.device.mark_used(step)
    assert statuses.count(200) == 1, f"one code, one session under concurrency: {statuses}"
