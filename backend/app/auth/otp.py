"""OTP code generation and delivery providers.

Providers are injected. A provider delivers a code to a destination: a phone
number (E.164) for SMS providers, an email address for email providers. The
mock, console and staging providers exist for development, tests and staging
only; settings refuse them in production, and nothing falls back to them."""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TextIO


class OtpDeliveryError(Exception):
    """The code could not be delivered. Never include the code in the message."""


def generate_code() -> str:
    """Six random digits from the OS CSPRNG."""
    return f"{secrets.randbelow(1_000_000):06d}"


def mask_phone(phone_e164: str) -> str:
    """+919876543210 -> +91******3210."""
    return f"{phone_e164[:3]}{'*' * 6}{phone_e164[-4:]}"


def mask_destination(destination: str) -> str:
    """A phone number or an email address, with the middle hidden."""
    if "@" in destination:
        local, _, domain = destination.partition("@")
        return f"{local[:1]}***@{domain}"
    return mask_phone(destination)


class OtpProvider(Protocol):
    def new_code(self) -> str: ...

    async def deliver(self, destination: str, code: str) -> None: ...


class DisabledOtpProvider:
    """Sends nothing. Every request fails with a delivery error (HTTP 503)."""

    def new_code(self) -> str:
        return generate_code()

    async def deliver(self, destination: str, code: str) -> None:
        raise OtpDeliveryError("no OTP provider is configured")


class ConsoleOtpProvider:
    """Prints the code to the developer's interactive terminal.

    It writes straight to the process's original stderr, bypassing the logging
    pipeline, and only if that stream is a TTY. When output is piped, redirected
    to a file, or captured by Docker or CI, it refuses to print, so codes cannot
    reach application logs or shared log collectors."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream

    def new_code(self) -> str:
        return generate_code()

    async def deliver(self, destination: str, code: str) -> None:
        stream = self._stream if self._stream is not None else sys.__stderr__
        if stream is None or not stream.isatty():
            raise OtpDeliveryError("console OTP provider needs an interactive terminal")
        stream.write(f"[tradeo local dev] OTP for {mask_destination(destination)}: {code}\n")
        stream.flush()


class MockOtpProvider:
    """Development and automated tests only (settings refuse it elsewhere).

    Uses a fixed, publicly known code, so it is never a real second factor.
    Deliveries are recorded in memory and sent nowhere."""

    def __init__(self, code: str = "123456") -> None:
        self._code = code
        self.sent: list[tuple[str, str]] = []

    def new_code(self) -> str:
        return self._code

    async def deliver(self, destination: str, code: str) -> None:
        self.sent.append((destination, code))


class StagingFileOtpProvider:
    """Staging only: writes the latest code per allowlisted number to a private
    file that the operator reads on the server. Nothing is sent over a network
    and nothing reaches logs. A destination outside the allowlist is refused,
    so staging can never deliver to a real person.

    The file holds one JSON object: {destination: {"code", "expiresAt"}} with
    mode 0600, replaced atomically on every delivery."""

    def __init__(
        self,
        path: str,
        allowlist: list[str],
        *,
        ttl_seconds: int = 300,
        clock_seconds: Callable[[], float] = time.time,
    ) -> None:
        self._path = Path(path)
        self._allow = frozenset(allowlist)
        self._ttl = ttl_seconds
        self._now = clock_seconds

    def new_code(self) -> str:
        return generate_code()

    async def deliver(self, destination: str, code: str) -> None:
        if destination not in self._allow:
            raise OtpDeliveryError("destination is not on the staging allowlist")
        try:
            self._write(destination, code)
        except OSError as exc:
            raise OtpDeliveryError("staging OTP file is not writable") from exc

    def _write(self, destination: str, code: str) -> None:
        now = self._now()
        entries = read_staging_codes(self._path, now=now)
        entries[destination] = {"code": code, "expiresAt": now + self._ttl}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".otp-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump(entries, handle)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def read_staging_codes(path: Path, *, now: float) -> dict[str, dict[str, float | str]]:
    """Unexpired entries of the staging file; an absent or damaged file is empty."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        k: v
        for k, v in raw.items()
        if isinstance(v, dict)
        and isinstance(v.get("expiresAt"), int | float)
        and v["expiresAt"] > now
    }
