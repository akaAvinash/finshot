from __future__ import annotations

import io
import re
from datetime import timedelta

import pytest

from app.auth import csrf
from app.auth.cookies import clear_cookie, set_cookie
from app.auth.crypto import Keys, hmac_hex
from app.auth.otp import (
    ConsoleOtpProvider,
    DisabledOtpProvider,
    OtpDeliveryError,
    generate_code,
    mask_phone,
)
from app.auth.service import device_label_from_user_agent
from tests.support import FakeClock

KEYS = Keys.from_secret("unit-test-secret-0123456789abcdef0123456789")
OTHER = Keys.from_secret("another-secret-0123456789abcdef0123456789ab")


def claims(context: csrf.Context = "pre_login", cid: str = "abc", clock: FakeClock | None = None):
    clock = clock or FakeClock()
    return clock, csrf.CsrfClaims(context, cid, clock.now + timedelta(minutes=30))


def test_csrf_token_roundtrip() -> None:
    clock, c = claims("session", "11111111-1111-1111-1111-111111111111")
    token = csrf.issue(KEYS, c)
    out = csrf.verify(KEYS, token, clock.now)
    assert out is not None
    assert (out.context, out.context_id) == ("session", c.context_id)
    assert 32 <= len(token) <= 512


def test_csrf_token_rejects_tampering() -> None:
    clock, c = claims("pre_login", "ctx1")
    token = csrf.issue(KEYS, c)
    parts = token.split(".")
    # Re-bind to a session context, change the id, or extend the expiry.
    for index, value in ((1, "ses"), (2, "other"), (3, str(int(parts[3]) + 9999))):
        forged = parts.copy()
        forged[index] = value
        assert csrf.verify(KEYS, ".".join(forged), clock.now) is None
    assert csrf.verify(OTHER, token, clock.now) is None  # different secret
    assert csrf.verify(KEYS, token[:-2] + "xx", clock.now) is None


def test_csrf_token_expires() -> None:
    clock, c = claims()
    token = csrf.issue(KEYS, c)
    clock.advance(30 * 60 + 1)
    assert csrf.verify(KEYS, token, clock.now) is None


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "x",
        "v1.a.b",
        "v2.pre.a.1.n.s",
        "v1.zzz.a.1.n.s",
        "v1.pre.a.NaN.n.s",
        "." * 5,
        "a" * 600,
    ],
)
def test_csrf_verify_rejects_garbage(bad: str | None) -> None:
    assert csrf.verify(KEYS, bad, FakeClock().now) is None


def test_csrf_tokens_are_unique_per_issue() -> None:
    _, c = claims()
    assert csrf.issue(KEYS, c) != csrf.issue(KEYS, c)


def test_keys_are_separated_by_purpose() -> None:
    assert len({KEYS.otp, KEYS.session, KEYS.csrf, KEYS.identifier}) == 4
    assert hmac_hex(KEYS.otp, "x") != hmac_hex(KEYS.session, "x")


def test_generated_codes_are_six_digits() -> None:
    codes = {generate_code() for _ in range(200)}
    assert all(re.fullmatch(r"[0-9]{6}", c) for c in codes)
    assert len(codes) > 150  # not constant


def test_mask_phone() -> None:
    assert mask_phone("+919876543210") == "+91******3210"


async def test_disabled_provider_always_fails() -> None:
    provider = DisabledOtpProvider()
    with pytest.raises(OtpDeliveryError):
        await provider.deliver("+919876543210", provider.new_code())


class _Stream(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


async def test_console_provider_prints_only_to_an_interactive_terminal() -> None:
    tty, piped = _Stream(True), _Stream(False)
    await ConsoleOtpProvider(tty).deliver("+919876543210", "654321")
    assert "654321" in tty.getvalue() and "+91******3210" in tty.getvalue()
    assert "9876543210" not in tty.getvalue()
    with pytest.raises(OtpDeliveryError):
        await ConsoleOtpProvider(piped).deliver("+919876543210", "654321")
    assert piped.getvalue() == ""


def test_cookie_helpers_set_host_only_secure_cookies() -> None:
    from starlette.responses import Response

    from tests.support import parse_set_cookie

    response = Response()
    set_cookie(response, "__Host-tradeo_session", "tok")
    clear_cookie(response, "__Host-tradeo_csrf")
    lines = response.headers.getlist("set-cookie")
    assert len(lines) == 2
    first, second = (parse_set_cookie(x) for x in lines)
    for cookie in (first, second):
        attrs = cookie["attrs"]
        assert attrs["httponly"] is True and attrs["secure"] is True
        assert str(attrs["samesite"]).lower() == "lax" and attrs["path"] == "/"
        assert "domain" not in attrs
    assert "max-age" not in first["attrs"]
    assert second["attrs"]["max-age"] == "0" and second["value"] in ('""', "")


@pytest.mark.parametrize(
    ("ua", "label"),
    [
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit Chrome/120.0 Safari/537",
            "Chrome on macOS",
        ),
        ("Mozilla/5.0 (Windows NT 10.0) Gecko Firefox/121.0", "Firefox on Windows"),
        ("curl/8.0", "Browser on unknown OS"),
        (None, None),
        ("", None),
    ],
)
def test_device_label_is_coarse(ua: str | None, label: str | None) -> None:
    assert device_label_from_user_agent(ua) == label
