"""Check the running API against contracts/openapi.yaml (the source of truth).

Responses are validated with the contract's own JSON Schemas, so a drift in
field names, required fields or enum values fails here."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

from tests.support import PHONE, Browser

pytestmark = pytest.mark.integration

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "openapi.yaml"


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    if not CONTRACT_PATH.exists():
        pytest.fail(f"contract not found at {CONTRACT_PATH}")
    loaded: dict[str, Any] = yaml.safe_load(CONTRACT_PATH.read_text())
    return loaded


def check(contract: dict[str, Any], schema_name: str, payload: Any) -> None:
    schema = {
        "$ref": f"#/components/schemas/{schema_name}",
        "components": contract["components"],
    }
    errors = list(
        Draft202012Validator(
            schema, format_checker=Draft202012Validator.FORMAT_CHECKER
        ).iter_errors(payload)
    )
    assert not errors, [e.message for e in errors]


def test_every_contract_auth_operation_is_implemented(
    contract: dict[str, Any], browser: Browser
) -> None:
    served = browser.get("/openapi.json").json()["paths"]
    for path, operations in contract["paths"].items():
        if not path.startswith(("/api/v1/auth/", "/api/v1/settings/")):
            continue
        assert path in served, f"{path} missing from the API"
        for method in operations:
            assert method in served[path], f"{method.upper()} {path} missing"


def test_responses_match_contract_schemas(contract: dict[str, Any], browser: Browser) -> None:
    csrf = browser.get_csrf()
    check(contract, "CsrfToken", csrf.json())

    challenge = browser.request_otp()
    assert challenge.status_code == 202
    check(contract, "OtpChallenge", challenge.json())

    verified = browser.verify(challenge.json()["challengeId"], "123456")
    check(contract, "OtpVerifyResponse", verified.json())
    assert "csrfToken" in verified.json()  # required by the contract

    check(contract, "AuthSession", browser.get("/api/v1/auth/me").json())
    check(contract, "SessionList", browser.get("/api/v1/auth/sessions").json())
    assert verified.json()["user"]["phoneMasked"] != PHONE


def test_error_bodies_match_contract_schema(contract: dict[str, Any], browser: Browser) -> None:
    responses: list[Any] = [browser.get("/api/v1/auth/me")]  # 401 UNAUTHENTICATED
    browser.get_csrf()
    responses.append(browser.request_otp(headers=browser.headers(csrf="bad" * 20)))  # 403
    responses.append(browser.post("/api/v1/auth/otp/request", json={"phone": "123"}))  # 400
    challenge = browser.request_otp().json()
    responses.append(browser.verify(challenge["challengeId"], "000000"))  # 401 INVALID_OTP
    seen = {r.json()["code"] for r in responses}
    assert seen == {"UNAUTHENTICATED", "CSRF_FAILED", "INVALID_REQUEST", "INVALID_OTP"}
    for response in responses:
        check(contract, "AuthError", response.json())


def test_rate_limited_error_matches_contract(contract: dict[str, Any], make_app: Any) -> None:
    browser = Browser(make_app(otp_resend_cooldown_seconds=30))
    browser.get_csrf()
    browser.request_otp()
    limited = browser.request_otp()
    assert limited.status_code == 429
    check(contract, "AuthError", limited.json())
    assert "retryAfterSeconds" in limited.json() and "Retry-After" in limited.headers


def test_delivery_unavailable_matches_contract(
    contract: dict[str, Any], browser: Browser, provider: Any
) -> None:
    browser.get_csrf()
    provider.fail = True
    response = browser.request_otp()
    check(contract, "AuthError", response.json())


def test_status_codes_used_are_documented_in_the_contract(
    contract: dict[str, Any], browser: Browser
) -> None:
    documented = {
        (path, method): set(op["responses"])
        for path, ops in contract["paths"].items()
        for method, op in ops.items()
    }
    login = browser.login()
    assert str(login.status_code) in documented[("/api/v1/auth/otp/verify", "post")]
    assert str(browser.get("/api/v1/auth/me").status_code) in documented[("/api/v1/auth/me", "get")]
    assert "204" in documented[("/api/v1/auth/logout", "post")]
    assert "204" in documented[("/api/v1/auth/logout-all", "post")]


def test_settings_bodies_match_contract_schemas(contract: dict[str, Any], browser: Browser) -> None:
    browser.login()
    profile = browser.get("/api/v1/settings/profile")
    check(contract, "SettingsProfile", profile.json())
    saved = browser.send(
        "PUT",
        "/api/v1/settings/profile",
        json={"displayName": "Asha", "timezone": "UTC"},
        headers=browser.headers(),
    )
    check(contract, "SettingsProfile", saved.json())
    bad = browser.send(
        "PUT",
        "/api/v1/settings/profile",
        json={"displayName": " ", "timezone": "UTC"},
        headers=browser.headers(),
    )
    check(contract, "AuthError", bad.json())
    gone = browser.send(
        "DELETE",
        "/api/v1/auth/sessions/00000000-0000-4000-8000-000000000000",
        headers=browser.headers(),
    )
    check(contract, "AuthError", gone.json())  # STEP_UP_REQUIRED before 404


def test_display_name_contract_pattern_agrees_with_the_server(
    contract: dict[str, Any], browser: Browser
) -> None:
    """Names the schema accepts are saved; names it rejects get 400."""
    browser.login()
    for name in ("A", "  Avi nash  ", "a" * 48 + " ", "a" * 49, " ", "", "A\x00B", "A\tB"):
        body = {"displayName": name, "timezone": "UTC"}
        errors = list(
            Draft202012Validator(
                {
                    "$ref": "#/components/schemas/SettingsProfileUpdate",
                    "components": contract["components"],
                }
            ).iter_errors(body)
        )
        status = browser.send(
            "PUT", "/api/v1/settings/profile", json=body, headers=browser.headers()
        ).status_code
        assert (not errors) == (status == 200), (name, errors, status)
