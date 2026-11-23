"""Shared test helpers: injected OTP provider, controllable clock, a browser-like client."""

from __future__ import annotations

import asyncio
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

    def request_otp(self, phone: str = PHONE, **kwargs: Any) -> Any:
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

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.send("POST", path, headers=kwargs.pop("headers", self.headers()), **kwargs)


def new_id() -> str:
    return str(uuid.uuid4())
