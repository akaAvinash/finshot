"""OTP code generation and delivery providers.

Providers are injected. Production code has no fixed-code provider; tests inject
their own. The console provider exists for manual local testing only."""

from __future__ import annotations

import secrets
import sys
from typing import Protocol, TextIO


class OtpDeliveryError(Exception):
    """The code could not be delivered. Never include the code in the message."""


def generate_code() -> str:
    """Six random digits from the OS CSPRNG."""
    return f"{secrets.randbelow(1_000_000):06d}"


def mask_phone(phone_e164: str) -> str:
    """+919876543210 -> +91******3210."""
    return f"{phone_e164[:3]}{'*' * 6}{phone_e164[-4:]}"


class OtpProvider(Protocol):
    def new_code(self) -> str: ...

    async def deliver(self, phone_e164: str, code: str) -> None: ...


class DisabledOtpProvider:
    """Sends nothing. Every request fails with a delivery error (HTTP 503)."""

    def new_code(self) -> str:
        return generate_code()

    async def deliver(self, phone_e164: str, code: str) -> None:
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

    async def deliver(self, phone_e164: str, code: str) -> None:
        stream = self._stream if self._stream is not None else sys.__stderr__
        if stream is None or not stream.isatty():
            raise OtpDeliveryError("console OTP provider needs an interactive terminal")
        stream.write(f"[tradeo local dev] OTP for {mask_phone(phone_e164)}: {code}\n")
        stream.flush()
