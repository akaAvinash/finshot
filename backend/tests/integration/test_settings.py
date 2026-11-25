"""Profile settings and ending other sessions (real Postgres and Redis)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from tests.integration.test_auth_stepup import audit_actions, code_for, enroll_and_confirm
from tests.support import PHONE, Browser, FakeClock, FixedOtpProvider, db_rows

MakeApp = Callable[..., TestClient]
PROFILE = "/api/v1/settings/profile"


def other_browser(client: TestClient) -> Browser:
    other = Browser(client)
    other.login()
    return other


# ------------------------------------------------------------------ profile


def test_profile_defaults_then_saves_and_shows_in_me(browser: Browser, db_url: str) -> None:
    browser.login()
    first = browser.get(PROFILE)
    assert first.status_code == 200
    assert first.json()["displayName"] is None
    assert first.json()["timezone"] == "Asia/Kolkata"
    assert set(first.json()) == {"displayName", "timezone", "phoneMasked"}
    assert PHONE not in first.text

    saved = browser.send(
        "PUT",
        PROFILE,
        json={"displayName": "  Avi nash  ", "timezone": "UTC"},
        headers=browser.headers(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["displayName"] == "Avi nash"
    assert saved.json()["timezone"] == "UTC"
    assert browser.get(PROFILE).json()["displayName"] == "Avi nash"
    assert browser.get("/api/v1/auth/me").json()["user"]["displayName"] == "Avi nash"
    # Saving the same values again succeeds.
    again = browser.send(
        "PUT",
        PROFILE,
        json={"displayName": "Avi nash", "timezone": "UTC"},
        headers=browser.headers(),
    )
    assert again.status_code == 200
    assert audit_actions(db_url).count("settings.profile_updated") == 2
    meta = db_rows(
        db_url,
        "SELECT metadata_redacted AS m FROM audit_events WHERE action = 'settings.profile_updated'",
    )
    assert all(r["m"] == {} for r in meta)


def test_profile_validation(browser: Browser) -> None:
    browser.login()

    def put(body: dict[str, Any]) -> Any:
        return browser.send("PUT", PROFILE, json=body, headers=browser.headers())

    ok_name = "a" * 48
    assert put({"displayName": ok_name + " ", "timezone": "UTC"}).status_code == 200
    for bad in ("", "   ", "a" * 49, "A\x00B", "A\tB", "A\x7fB", "x" * 201):
        response = put({"displayName": bad, "timezone": "UTC"})
        assert response.status_code == 400, bad
        assert response.json()["code"] == "INVALID_REQUEST"
    assert put({"displayName": "Ok", "timezone": "America/New_York"}).status_code == 400
    assert put({"displayName": "Ok"}).status_code == 400
    assert (
        put({"displayName": "Ok", "timezone": "UTC", "phone": "+919000000000"}).status_code == 400
    )


def test_profile_needs_a_session_then_csrf(browser: Browser, client: TestClient) -> None:
    assert browser.get(PROFILE).status_code == 401
    unauthenticated = browser.send("PUT", PROFILE, json={}, headers=browser.headers())
    assert unauthenticated.status_code == 401
    browser.login()
    no_csrf = browser.send(
        "PUT",
        PROFILE,
        json={"displayName": "Ok", "timezone": "UTC"},
        headers=browser.headers(csrf="wrong"),
    )
    assert no_csrf.status_code == 403
    assert no_csrf.json()["code"] == "CSRF_FAILED"


# --------------------------------------------------------- revoke a session


def revoke(browser: Browser, session_id: str, **kwargs: Any) -> Any:
    return browser.send(
        "DELETE", f"/api/v1/auth/sessions/{session_id}", headers=browser.headers(), **kwargs
    )


def session_ids(browser: Browser) -> tuple[str, list[str]]:
    rows = browser.get("/api/v1/auth/sessions").json()["sessions"]
    current = next(r["id"] for r in rows if r["current"])
    return current, [r["id"] for r in rows if not r["current"]]


def test_revoke_needs_step_up_and_ends_the_other_session(
    client: TestClient, clock: FakeClock, db_url: str
) -> None:
    first = Browser(client)
    first.login()
    second = other_browser(client)
    _, others = session_ids(first)
    assert len(others) == 1

    blocked = revoke(first, others[0])
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "STEP_UP_REQUIRED"
    assert second.get("/api/v1/auth/me").status_code == 200  # nothing changed

    secret = enroll_and_confirm(first, clock)
    clock.advance(31)
    assert (
        first.post("/api/v1/auth/step-up", json={"code": code_for(secret, clock)}).status_code
        == 200
    )

    assert revoke(first, others[0]).status_code == 204
    assert second.get("/api/v1/auth/me").status_code == 401
    assert first.get("/api/v1/auth/me").status_code == 200
    assert "session.revoked" in audit_actions(db_url)
    rows = db_rows(
        db_url, "SELECT metadata_redacted AS m FROM audit_events WHERE action = 'session.revoked'"
    )
    assert rows[0]["m"] == {}

    again = revoke(first, others[0])
    assert again.status_code == 404
    assert again.json()["code"] == "SESSION_NOT_FOUND"


def test_revoke_rejects_current_unknown_and_foreign_sessions(
    client: TestClient, clock: FakeClock, db_url: str, provider: FixedOtpProvider
) -> None:
    first = Browser(client)
    first.login()
    secret = enroll_and_confirm(first, clock)
    clock.advance(31)
    first.post("/api/v1/auth/step-up", json={"code": code_for(secret, clock)})
    current, _ = session_ids(first)

    own = revoke(first, current)
    assert own.status_code == 409
    assert own.json()["code"] == "CURRENT_SESSION"
    assert first.get("/api/v1/auth/me").status_code == 200

    assert revoke(first, "00000000-0000-4000-8000-000000000000").status_code == 404
    assert revoke(first, "not-a-uuid").status_code == 404

    # Another user's session id is indistinguishable from an unknown one.
    stranger_phone = "+919876500000"
    stranger = Browser(client)
    stranger.login(phone=stranger_phone)
    stranger_current, _ = session_ids(stranger)
    foreign = revoke(first, stranger_current)
    assert foreign.status_code == 404
    assert stranger.get("/api/v1/auth/me").status_code == 200


def test_revoke_checks_csrf_before_step_up(client: TestClient) -> None:
    first = Browser(client)
    first.login()
    response = first.send(
        "DELETE",
        "/api/v1/auth/sessions/00000000-0000-4000-8000-000000000000",
        headers=first.headers(csrf="wrong"),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert (
        first.send(
            "DELETE", "/api/v1/auth/sessions/00000000-0000-4000-8000-000000000000", headers={}
        ).status_code
        == 403
    )
