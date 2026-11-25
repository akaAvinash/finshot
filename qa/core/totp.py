"""Independent RFC 6238 TOTP oracle (HMAC-SHA-1, 30-second steps).

Written from the RFC, not from the product code, so a shared bug cannot make
both sides agree. Self-tested against the RFC 6238 Appendix B vectors.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

STEP_SECONDS = 30


def hotp(key: bytes, counter: int, digits: int = 6, digest: str = "sha1") -> str:
    mac = hmac.new(key, struct.pack(">Q", counter), getattr(hashlib, digest)).digest()
    offset = mac[-1] & 0x0F
    binary = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**digits)).zfill(digits)


def step_at(epoch: float) -> int:
    return int(epoch // STEP_SECONDS)


def decode_base32(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


@dataclass(frozen=True)
class OtpauthUri:
    label: str
    issuer: str | None
    secret: str
    algorithm: str
    digits: int
    period: int


def parse_otpauth(uri: str) -> OtpauthUri:
    parsed = urlparse(uri)
    if parsed.scheme != "otpauth" or parsed.netloc != "totp":
        raise ValueError("not an otpauth://totp URI")
    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    return OtpauthUri(
        label=unquote(parsed.path.lstrip("/")),
        issuer=query.get("issuer"),
        secret=query.get("secret", ""),
        algorithm=query.get("algorithm", "SHA1").upper(),
        digits=int(query.get("digits", "6")),
        period=int(query.get("period", "30")),
    )


@dataclass
class TotpDevice:
    """A simulated authenticator app that knows which steps the server has consumed.

    The server accepts each step once and only steps greater than the last
    accepted one, within +/-1 step of its clock. `fresh_code()` returns a code
    the server should accept, waiting for the next step when needed.
    """

    secret: str
    last_used_step: int = 0
    clock: object = field(default=time.time)

    def code_for_step(self, step: int) -> str:
        return hotp(decode_base32(self.secret), step)

    def now_step(self) -> int:
        return step_at(self.clock())  # type: ignore[operator]

    def fresh_code(self) -> tuple[str, int]:
        while True:
            now = self.clock()  # type: ignore[operator]
            step = step_at(now)
            remaining = STEP_SECONDS - (now % STEP_SECONDS)
            # Avoid the last 2 seconds of a step: the request may land in the next one.
            if step > self.last_used_step and remaining > 2:
                return self.code_for_step(step), step
            if step + 1 > self.last_used_step:
                # +1 step is inside the server's allowed skew.
                return self.code_for_step(step + 1), step + 1
            time.sleep(min(remaining + 0.2, STEP_SECONDS))

    def mark_used(self, step: int) -> None:
        self.last_used_step = max(self.last_used_step, step)
