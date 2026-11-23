"""Key derivation and HMAC helpers.

One master secret (AUTH_SECRET_KEY) is expanded into separate keys per purpose,
so a digest made for one purpose can never be replayed as another."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

_SEP = "\x1f"


def _derive(master: bytes, label: str) -> bytes:
    return hmac.new(master, f"tradeo/v1/{label}".encode(), hashlib.sha256).digest()


@dataclass(frozen=True)
class Keys:
    otp: bytes
    session: bytes
    csrf: bytes
    identifier: bytes  # hashing IPs/phones for rate-limit keys and audit logs

    @classmethod
    def from_secret(cls, secret: str) -> Keys:
        master = secret.encode()
        return cls(
            otp=_derive(master, "otp"),
            session=_derive(master, "session"),
            csrf=_derive(master, "csrf"),
            identifier=_derive(master, "identifier"),
        )


def hmac_hex(key: bytes, *parts: str) -> str:
    return hmac.new(key, _SEP.join(parts).encode(), hashlib.sha256).hexdigest()


def hmac_bytes(key: bytes, *parts: str) -> bytes:
    return hmac.new(key, _SEP.join(parts).encode(), hashlib.sha256).digest()


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
