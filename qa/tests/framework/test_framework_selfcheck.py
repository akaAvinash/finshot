"""Self-tests for the QA framework itself: an oracle that is wrong makes every test wrong."""

from __future__ import annotations

import pytest

from qa.core.client import parse_set_cookie
from qa.core.contract import load_contract
from qa.core.redaction import redact
from qa.core.totp import hotp, parse_otpauth

pytestmark = [pytest.mark.suite("framework"), pytest.mark.severity("high")]

RFC6238_SHA1_KEY = b"12345678901234567890"


@pytest.mark.req("QA-FW-001")
@pytest.mark.parametrize(
    ("epoch", "expected8"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_totp_oracle_matches_rfc6238_vectors(epoch, expected8):
    assert hotp(RFC6238_SHA1_KEY, epoch // 30, digits=8) == expected8


@pytest.mark.req("QA-FW-001")
def test_hotp_matches_rfc4226_vectors():
    expected = ["755224", "287082", "359152", "969429", "338314", "254676", "287922", "162583", "399871", "520489"]
    assert [hotp(RFC6238_SHA1_KEY, i) for i in range(10)] == expected


@pytest.mark.req("QA-FW-001")
def test_otpauth_parser():
    u = parse_otpauth("otpauth://totp/Tradeo:%2B91%2A%2A3210?secret=ABCDEFGHIJKLMNOPQRSTUVWXYZ234567&issuer=Tradeo")
    assert u.secret == "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    assert (u.algorithm, u.digits, u.period) == ("SHA1", 6, 30)
    with pytest.raises(ValueError):
        parse_otpauth("https://example.com")


@pytest.mark.req("QA-FW-002")
def test_contract_validator_accepts_valid_and_flags_invalid():
    c = load_contract()
    good = {"csrfToken": "x" * 40, "context": "pre_login", "expiresAt": "2026-11-25T10:00:00Z"}
    assert c.validate("GET", "/api/v1/auth/csrf", 200, "application/json", good) == []
    bad = {"csrfToken": "short", "context": "admin"}
    problems = c.validate("GET", "/api/v1/auth/csrf", 200, "application/json", bad)
    text = " ".join(map(str, problems))
    assert "expiresAt" in text and "admin" in text and "short" in text


@pytest.mark.req("QA-FW-002")
def test_contract_validator_flags_undocumented_status_and_path():
    c = load_contract()
    assert c.validate("GET", "/api/v1/auth/csrf", 418, "application/json", {})
    assert c.validate("GET", "/api/v1/nope", 200, "application/json", {})
    assert c.operation("DELETE", "/api/v1/auth/sessions/0b7c6b1e-0000-4000-8000-000000000000")


@pytest.mark.req("QA-FW-003")
def test_redaction_hides_secrets():
    raw = (
        'Set-Cookie: __Host-tradeo_session=abc123; {"csrfToken": "tok", "secret": "S", "code": "123456"} '
        "+919876543210 ABCDE-FGHIJ postgresql+asyncpg://u:pw@h/db sk-ant-abcdefghijklmnop ghp_" + "a" * 36
    )
    out = redact(raw)
    for leaked in ("abc123", '"tok"', "123456", "9876543210", "ABCDE-FGHIJ", ":pw@", "sk-ant-abc", "ghp_aaaa"):
        assert leaked not in out, leaked


@pytest.mark.req("QA-FW-004")
def test_set_cookie_parser_reads_attributes():
    c = parse_set_cookie("__Host-tradeo_csrf=v; Path=/; Secure; HttpOnly; SameSite=Lax")
    assert (c.name, c.value) == ("__Host-tradeo_csrf", "v")
    assert c.attrs["secure"] == c.attrs["httponly"] == "true"
    assert c.attrs["samesite"] == "Lax" and not c.cleared
    assert parse_set_cookie("__Host-tradeo_session=; Path=/; Max-Age=0").cleared
