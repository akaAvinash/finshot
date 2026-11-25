"""Setup required (contract 0.10.0): a session whose account has no active
authenticator may only set one up. Every other session operation answers
403 TOTP_SETUP_REQUIRED after the 401 check and before CSRF, and changes
nothing. The restricted list is read from the contract, so a new operation
cannot slip past the rule."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.integration.test_auth_stepup import enroll_and_confirm
from tests.support import OTHER_PHONE, PHONE, Browser, FakeClock, db_rows

CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"
EXEMPT = {
    "getCsrfToken",
    "getCurrentUser",
    "logout",
    "logoutAll",
    "enrollTotp",
    "confirmTotp",
    # Sign-in operations: they take an optional session, not a required one.
    "requestOtp",
    "verifyOtp",
    "loginWithTotp",
    "loginWithRecoveryCode",
}
FILL = {
    "sessionId": "00000000-0000-0000-0000-000000000001",
    "provider": "demo",
    "runId": "00000000-0000-0000-0000-000000000002",
    "alertId": "00000000-0000-0000-0000-000000000003",
}


def restricted_operations() -> list[tuple[str, str, str]]:
    spec: dict[str, Any] = yaml.safe_load(CONTRACT.read_text())
    found: list[tuple[str, str, str]] = []
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not op.get("security") or op["operationId"] in EXEMPT:
                continue
            url = path
            for name, value in FILL.items():
                url = url.replace("{" + name + "}", value)
            found.append((op["operationId"], method.upper(), url))
    return found


OPERATIONS = restricted_operations()


def test_the_contract_lists_the_restricted_operations() -> None:
    assert len(OPERATIONS) >= 25  # guards against the parser silently finding none


@pytest.mark.parametrize(("operation", "method", "url"), OPERATIONS)
def test_restricted_operation_is_setup_required_before_csrf(
    browser: Browser, operation: str, method: str, url: str
) -> None:
    browser.login()
    # No CSRF token and no Origin: setup required is answered first.
    bare = browser.send(method, url, headers={}, json={})
    assert bare.status_code == 403, (operation, bare.text)
    assert bare.json()["code"] == "TOTP_SETUP_REQUIRED"
    assert browser.send(method, url, headers=browser.headers(), json={}).status_code == 403


@pytest.mark.parametrize(("operation", "method", "url"), OPERATIONS)
def test_restricted_operation_without_a_session_is_401(
    browser: Browser, operation: str, method: str, url: str
) -> None:
    response = browser.send(method, url, headers={}, json={})
    assert response.status_code == 401, (operation, response.text)


def test_a_valid_write_is_rejected_and_changes_nothing(browser: Browser, db_url: str) -> None:
    browser.login()
    sql_user = "SELECT display_name, timezone FROM users WHERE phone_e164 = :p"
    before_user = db_rows(db_url, sql_user, p=PHONE)
    before_audit = db_rows(db_url, "SELECT count(*) AS n FROM audit_events")
    response = browser.send(
        "PUT",
        "/api/v1/settings/profile",
        json={"displayName": "Changed Name", "timezone": "UTC"},
        headers=browser.headers(),  # valid CSRF and Origin
    )
    assert response.status_code == 403 and response.json()["code"] == "TOTP_SETUP_REQUIRED"
    assert db_rows(db_url, sql_user, p=PHONE) == before_user
    assert db_rows(db_url, "SELECT count(*) AS n FROM audit_events") == before_audit


def test_exempt_operations_work_before_setup(browser: Browser, clock: FakeClock) -> None:
    login = browser.login()
    assert login.json()["user"]["totpEnabled"] is False
    assert browser.get("/api/v1/auth/csrf").status_code == 200
    me = browser.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["user"]["totpEnabled"] is False
    assert browser.post("/api/v1/auth/totp/enroll").status_code == 200
    # Whatever it answers, confirm must not be setup required.
    confirm = browser.post("/api/v1/auth/totp/confirm", json={"code": "000000"})
    assert confirm.json().get("code") != "TOTP_SETUP_REQUIRED"
    assert browser.post("/api/v1/auth/logout").status_code == 204


def test_logout_all_works_before_setup(browser: Browser) -> None:
    browser.login()
    assert browser.post("/api/v1/auth/logout-all").status_code == 204
    assert browser.get("/api/v1/auth/me").status_code == 401


def test_confirming_an_authenticator_lifts_the_limit_on_every_session(
    browser: Browser, clock: FakeClock
) -> None:
    one = browser
    one.login()
    two = Browser(browser.client)
    two.login()
    assert two.get("/api/v1/settings/profile").status_code == 403
    enroll_and_confirm(one, clock)
    assert one.get("/api/v1/settings/profile").status_code == 200
    assert two.get("/api/v1/settings/profile").status_code == 200


def test_setup_required_is_per_account(browser: Browser, clock: FakeClock) -> None:
    browser.login()
    enroll_and_confirm(browser, clock)
    other = Browser(browser.client)
    other.login(phone=OTHER_PHONE)
    assert other.get("/api/v1/settings/profile").status_code == 403
    assert browser.get("/api/v1/settings/profile").status_code == 200
