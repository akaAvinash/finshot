"""SMTP email delivery for one-time codes.

The SMTP transport is injected (tests pass a fake; production uses stdlib
smtplib in a worker thread with a hard timeout). Credentials come from
settings as SecretStr and are used only to log in: they never appear in an
exception message, a log line or a delivered message. Failures raise
OtpDeliveryError with a fixed reason, never the server's reply text."""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from typing import Protocol

from pydantic import SecretStr

from app.auth.otp import OtpDeliveryError, generate_code


class SmtpTransport(Protocol):
    def send(self, message: EmailMessage) -> None:
        """Send or raise. May block: it runs in a worker thread."""


class StdlibSmtpTransport:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: SecretStr,
        starttls: bool,
        timeout: float,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._starttls = starttls
        self._timeout = timeout

    def send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as client:
            if self._starttls:
                client.starttls(context=ssl.create_default_context())
            client.login(self._username, self._password.get_secret_value())
            client.send_message(message)


class SmtpOtpProvider:
    def __init__(
        self,
        transport: SmtpTransport,
        *,
        sender: str,
        timeout: float,
        service_name: str = "Tradeo",
        run_in_thread: Callable[..., object] = asyncio.to_thread,
    ) -> None:
        self._transport = transport
        self._sender = sender
        self._timeout = timeout
        self._service = service_name
        self._run = run_in_thread

    def new_code(self) -> str:
        return generate_code()

    async def deliver(self, destination: str, code: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = destination
        message["Subject"] = f"Your {self._service} sign-in code"
        message.set_content(
            f"Your {self._service} sign-in code is {code}. It expires in 5 minutes.\n"
            "If you did not ask for it, ignore this email."
        )
        try:
            # The thread cannot be cancelled, so the wait is bounded here as
            # well as by the socket timeout inside the transport.
            await asyncio.wait_for(
                self._run(self._transport.send, message),  # type: ignore[arg-type]
                timeout=self._timeout + 5,
            )
        except TimeoutError as exc:
            raise OtpDeliveryError("smtp timed out") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise OtpDeliveryError(f"smtp failed ({type(exc).__name__})") from exc
