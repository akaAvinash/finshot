"""Shared test helpers: injected OTP provider, controllable clock, a browser-like client."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.auth.otp import OtpDeliveryError, generate_code

ORIGIN = "https://testserver"
PHONE = "+919876543210"
OTHER_PHONE = "+918765432109"


class FixedOtpProvider:
    """Test-only provider with a fixed code. Production code has no such path."""

    def __init__(self, code: str = "123456") -> None:
        self.code = code
        self.deliveries: list[tuple[str, str]] = []
        self.fail = False

    def new_code(self) -> str:
        return self.code

    async def deliver(self, phone_e164: str, code: str) -> None:
        if self.fail:
            raise OtpDeliveryError("provider down")
        self.deliveries.append((phone_e164, code))


class RecordingRandomProvider(FixedOtpProvider):
    """Random codes (like production) that tests can read back."""

    def new_code(self) -> str:
        return generate_code()


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 24, 6, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def db_rows(url: str, sql: str, **params: Any) -> list[dict[str, Any]]:
    async def run() -> list[dict[str, Any]]:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql), params)
                return [dict(r._mapping) for r in result] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(run())


def parse_set_cookie(line: str) -> dict[str, Any]:
    """'name=value; Path=/; Secure' -> {'name','value','attrs':{lowercased}}."""
    first, *rest = [p.strip() for p in line.split(";")]
    name, _, value = first.partition("=")
    attrs: dict[str, str | bool] = {}
    for part in rest:
        key, sep, val = part.partition("=")
        attrs[key.lower()] = val if sep else True
    return {"name": name, "value": value, "attrs": attrs}


class Browser:
    """A client that behaves like a browser against the API: keeps its own cookie
    jar, holds the CSRF token in memory, sends Origin on writes. Several browsers
    can share one running app (and so one event loop and one database pool)."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.csrf: str | None = None
        self.jar = httpx.Cookies()

    def activate(self) -> TestClient:
        """Load this browser's cookies into the shared client."""
        self.client.cookies.clear()
        for cookie in self.jar.jar:
            self.client.cookies.jar.set_cookie(cookie)
        return self.client

    def send(self, method: str, path: str, **kwargs: Any) -> Any:
        client = self.activate()
        try:
            return client.request(method, path, **kwargs)
        finally:
            self.jar = httpx.Cookies()
            for cookie in client.cookies.jar:
                self.jar.jar.set_cookie(cookie)

    def cookie(self, name: str) -> str | None:
        return self.jar.get(name)

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.send("GET", path, **kwargs)

    def headers(self, csrf: str | None = None, origin: str | None = ORIGIN) -> dict[str, str]:
        headers: dict[str, str] = {}
        token = csrf if csrf is not None else self.csrf
        if token is not None:
            headers["X-CSRF-Token"] = token
        if origin is not None:
            headers["Origin"] = origin
        return headers

    def get_csrf(self) -> Any:
        response = self.get("/api/v1/auth/csrf")
        if response.status_code == 200:
            self.csrf = response.json()["csrfToken"]
        return response

    def request_otp(self, phone: str = PHONE, *, invite: bool = True, **kwargs: Any) -> Any:
        """Sign-in is invite-only, so by default the number is invited first
        (pass invite=False to exercise the uninvited path)."""
        if invite:
            invite_phone(phone)
        return self.post(
            "/api/v1/auth/otp/request",
            json={"phone": phone},
            headers=kwargs.pop("headers", self.headers()),
            **kwargs,
        )

    def verify(self, challenge_id: str, code: str, **kwargs: Any) -> Any:
        response = self.post(
            "/api/v1/auth/otp/verify",
            json={"challengeId": challenge_id, "code": code},
            headers=kwargs.pop("headers", self.headers()),
            **kwargs,
        )
        if response.status_code == 200:
            self.csrf = response.json()["csrfToken"]
        return response

    def login(self, code: str = "123456", phone: str = PHONE) -> Any:
        self.get_csrf()
        challenge = self.request_otp(phone)
        assert challenge.status_code == 202, challenge.text
        response = self.verify(challenge.json()["challengeId"], code)
        assert response.status_code == 200, response.text
        return response

    def login_ready(self, code: str = "123456", phone: str = PHONE) -> Any:
        """Sign in and give the account an active authenticator, so the session
        is no longer limited to setting one up. Domain tests use this; the
        auth tests use `login` to exercise the setup-required limit."""
        deactivate_authenticator(phone)  # a code cannot start a session once one is active
        response = self.login(code, phone)
        activate_authenticator(phone)
        return response

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.send("POST", path, headers=kwargs.pop("headers", self.headers()), **kwargs)


def invite_phone(phone: str, email: str | None = None) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return
    db_rows(
        url,
        "INSERT INTO invites (phone_e164, email, created_at) VALUES (:p, :e, now())"
        " ON CONFLICT (phone_e164) DO UPDATE SET revoked_at = NULL,"
        " email = COALESCE(:e, invites.email)",
        p=phone,
        e=email,
    )


def activate_authenticator(phone: str) -> None:
    """Mark the invited user's authenticator confirmed directly in the database
    (the secret is a placeholder: nothing here signs in with it)."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return
    db_rows(
        url,
        "INSERT INTO totp_credentials (user_id, secret_enc, created_at, confirmed_at, last_step)"
        " SELECT id, :secret, now(), now(), 0 FROM users WHERE phone_e164 = :p"
        " ON CONFLICT (user_id) DO UPDATE SET confirmed_at = now(), pending_expires_at = NULL",
        p=phone,
        secret=b"test-placeholder",
    )


def deactivate_authenticator(phone: str) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return
    db_rows(
        url,
        "DELETE FROM totp_credentials WHERE user_id IN (SELECT id FROM users WHERE phone_e164 = :p)",
        p=phone,
    )


def new_id() -> str:
    return str(uuid.uuid4())
