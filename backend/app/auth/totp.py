"""TOTP (RFC 6238: HMAC-SHA-1, 6 digits, 30-second steps) and secret sealing.

Pure functions plus AES-GCM sealing of the stored secret. The sealing key is
derived from AUTH_SECRET_KEY (Keys.totp), and the user id is bound as associated data, so a
sealed secret copied to another user's row does not open."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import uuid
from urllib.parse import quote

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

STEP_SECONDS = 30
DIGITS = 6
SKEW_STEPS = 1
SECRET_BYTES = 20  # 160 bits, as RFC 4226 recommends


def new_secret() -> bytes:
    return secrets.token_bytes(SECRET_BYTES)


def secret_to_base32(secret: bytes) -> str:
    return base64.b32encode(secret).decode()


def otpauth_uri(secret: bytes, *, account: str, issuer: str = "Tradeo") -> str:
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret_to_base32(secret)}"
        f"&issuer={quote(issuer, safe='')}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def code_at(secret: bytes, step: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10**DIGITS:0{DIGITS}d}"


def current_step(now_epoch: float) -> int:
    return int(now_epoch // STEP_SECONDS)


def matching_step(secret: bytes, code: str, now_epoch: float) -> int | None:
    """The time step whose code equals `code`, within the allowed skew, or None.
    Every candidate is compared, so timing does not reveal which one matched."""
    now_step = current_step(now_epoch)
    match: int | None = None
    for step in range(now_step - SKEW_STEPS, now_step + SKEW_STEPS + 1):
        if hmac.compare_digest(code_at(secret, step), code) and match is None:
            match = step
    return match


def seal(key: bytes, user_id: uuid.UUID, secret: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, secret, user_id.bytes)


def unseal(key: bytes, user_id: uuid.UUID, sealed: bytes) -> bytes | None:
    try:
        return AESGCM(key).decrypt(sealed[:12], sealed[12:], user_id.bytes)
    except (InvalidTag, ValueError):
        return None
