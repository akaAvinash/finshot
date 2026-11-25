"""Local SMTP sink: the backend's real SMTP provider delivers here.

This exercises the production SMTP code path (EmailMessage, login, send)
without any external mail service. Nothing leaves 127.0.0.1. A failure mode
makes the sink answer with a 4xx/5xx so delivery-failure handling can be tested.
"""

from __future__ import annotations

import re
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from email import message_from_bytes, policy

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

CODE_RE = re.compile(r"\b(\d{6})\b")


@dataclass
class CapturedMail:
    to: str
    subject: str
    body: str
    received_at: float

    @property
    def code(self) -> str | None:
        match = CODE_RE.search(self.body)
        return match.group(1) if match else None


@dataclass
class _Handler:
    messages: list[CapturedMail] = field(default_factory=list)
    fail_with: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 - aiosmtpd hook name
        if self.fail_with:
            return self.fail_with
        msg = message_from_bytes(envelope.content, policy=policy.default)
        body = msg.get_body(preferencelist=("plain",))
        text = body.get_content() if body else ""
        with self.lock:
            for rcpt in envelope.rcpt_tos:
                self.messages.append(CapturedMail(rcpt.lower(), str(msg.get("Subject", "")), text, time.time()))
        return "250 OK"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class SmtpSink:
    def __init__(self) -> None:
        self.username = "qa-sink"
        self.password = secrets.token_urlsafe(16)
        self.port = _free_port()
        self._handler = _Handler()

        def authenticator(server, session, envelope, mechanism, auth_data):  # noqa: ANN001
            ok = (
                isinstance(auth_data, LoginPassword)
                and auth_data.login.decode() == self.username
                and auth_data.password.decode() == self.password
            )
            return AuthResult(success=ok)

        self._controller = Controller(
            self._handler,
            hostname="127.0.0.1",
            port=self.port,
            authenticator=authenticator,
            auth_require_tls=False,
            auth_required=True,
        )

    def start(self) -> None:
        self._controller.start()

    def stop(self) -> None:
        self._controller.stop()

    def clear(self) -> None:
        with self._handler.lock:
            self._handler.messages.clear()
        self._handler.fail_with = None

    def fail_deliveries(self, reply: str | None = "451 4.3.0 QA sink: temporary failure") -> None:
        self._handler.fail_with = reply

    def messages_to(self, address: str) -> list[CapturedMail]:
        with self._handler.lock:
            return [m for m in self._handler.messages if m.to == address.lower()]

    @property
    def all_messages(self) -> list[CapturedMail]:
        with self._handler.lock:
            return list(self._handler.messages)

    def wait_for_code(self, address: str, *, after: int = 0, timeout: float = 10.0) -> str:
        """Code from the (after+1)-th message to `address`."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            msgs = self.messages_to(address)
            if len(msgs) > after and msgs[after].code:
                return msgs[after].code  # type: ignore[return-value]
            time.sleep(0.05)
        raise AssertionError(f"no OTP email for {address} within {timeout}s")
