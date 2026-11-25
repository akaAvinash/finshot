"""Synthetic people who use Tradeo through its public interfaces.

Phone numbers are synthetic (+91 9 99xx xxxxx range picked per run) and email
addresses use the reserved `.invalid` TLD, so nothing can reach a real person
even if a test is misconfigured.
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Any

from qa.core.client import ApiClient
from qa.core.mail import SmtpSink
from qa.core.sut import Backend
from qa.core.totp import TotpDevice, parse_otpauth

_RUN_PREFIX = random.SystemRandom().randint(100, 999)
_COUNTER = itertools.count(1)


def synthetic_phone() -> str:
    n = next(_COUNTER)
    return f"+9199{_RUN_PREFIX:03d}{n:05d}"


@dataclass
class Person:
    backend: Backend
    sink: SmtpSink
    phone: str = field(default_factory=synthetic_phone)
    device: TotpDevice | None = None
    recovery_codes: list[str] = field(default_factory=list)
    clients: list[ApiClient] = field(default_factory=list)

    @property
    def email(self) -> str:
        return f"qa+{self.phone.lstrip('+')}@qa.tradeo.invalid"

    def new_client(self, name: str | None = None, **kw: Any) -> ApiClient:
        c = ApiClient(self.backend.base_url, name=name or f"{self.phone[-4:]}#{len(self.clients)}", **kw)
        self.clients.append(c)
        return c

    def invite(self, *, email: bool = True) -> None:
        args = ["invite", "add", self.phone]
        if email:
            args += ["--email", self.email]
        proc = self.backend.admin(*args)
        assert proc.returncode == 0, f"invite add failed: {proc.stderr[-500:]}"

    def request_email_code(self, client: ApiClient) -> dict[str, Any]:
        if not client.csrf_token:
            client.fetch_csrf()
        r = client.post("/auth/otp/request", {"phone": self.phone, "channel": "email"})
        assert r.status_code == 202, r.text
        return r.json()

    def register(self, client: ApiClient | None = None) -> ApiClient:
        """Invite, receive the emailed code from the SMTP sink, verify. Returns a signed-in client."""
        client = client or self.new_client()
        self.invite()
        before = len(self.sink.messages_to(self.email))
        challenge = self.request_email_code(client)
        code = self.sink.wait_for_code(self.email, after=before)
        r = client.post("/auth/otp/verify", {"challengeId": challenge["challengeId"], "code": code})
        assert r.status_code == 200, r.text
        client.adopt_login(r)
        return client

    def enroll(self, client: ApiClient) -> dict[str, Any]:
        r = client.post("/auth/totp/enroll")
        assert r.status_code == 200, r.text
        enrollment = r.json()
        uri = parse_otpauth(enrollment["otpauthUri"])
        assert uri.secret == enrollment["secret"]
        self.device = TotpDevice(enrollment["secret"])
        code, step = self.device.fresh_code()
        r = client.post("/auth/totp/confirm", {"code": code})
        assert r.status_code == 200, r.text
        self.device.mark_used(step)
        return enrollment

    def register_ready(self) -> ApiClient:
        """Registered and with an active authenticator (the normal state of an account)."""
        client = self.register()
        self.enroll(client)
        return client

    def login_totp(self, client: ApiClient | None = None) -> ApiClient:
        assert self.device is not None
        client = client or self.new_client()
        client.fetch_csrf()
        code, step = self.device.fresh_code()
        r = client.post("/auth/login/totp", {"phone": self.phone, "code": code})
        assert r.status_code == 200, r.text
        self.device.mark_used(step)
        client.adopt_login(r)
        return client

    def create_recovery_codes(self, client: ApiClient) -> list[str]:
        r = client.post("/auth/totp/recovery-codes")
        assert r.status_code == 200, r.text
        self.recovery_codes = list(r.json()["codes"])
        return self.recovery_codes
