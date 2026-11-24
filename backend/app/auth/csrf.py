"""Signed CSRF tokens bound to a context.

Token format (opaque to clients): ``v1.<ctx>.<context_id>.<expires>.<nonce>.<sig>``

- ``ctx`` is ``ses`` (bound to a server-side session id) or ``pre`` (bound to a
  random pre-login context id carried only inside the token).
- ``sig`` is HMAC-SHA256 over the other fields with a key derived from
  AUTH_SECRET_KEY, so tokens cannot be forged or re-bound to another context.
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.auth.crypto import Keys, constant_time_equal, hmac_bytes

Context = Literal["pre_login", "session"]
_CTX_CODE: dict[Context, str] = {"pre_login": "pre", "session": "ses"}
_CODE_CTX: dict[str, Context] = {v: k for k, v in _CTX_CODE.items()}


@dataclass(frozen=True)
class CsrfClaims:
    context: Context
    context_id: str
    expires_at: datetime


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_pre_login_context_id() -> str:
    return secrets.token_hex(16)


def issue(keys: Keys, claims: CsrfClaims) -> str:
    code = _CTX_CODE[claims.context]
    expires = str(int(claims.expires_at.timestamp()))
    nonce = secrets.token_urlsafe(12)
    signature = _b64(hmac_bytes(keys.csrf, "v1", code, claims.context_id, expires, nonce))
    return f"v1.{code}.{claims.context_id}.{expires}.{nonce}.{signature}"


def verify(keys: Keys, token: str | None, now: datetime) -> CsrfClaims | None:
    """Return the claims if the signature is valid and the token is unexpired."""
    if not token or len(token) > 512:
        return None
    parts = token.split(".")
    if len(parts) != 6 or parts[0] != "v1":
        return None
    _, code, context_id, expires, nonce, signature = parts
    context = _CODE_CTX.get(code)
    if context is None or not expires.isdigit():
        return None
    expected = _b64(hmac_bytes(keys.csrf, "v1", code, context_id, expires, nonce))
    if not constant_time_equal(expected, signature):
        return None
    expires_at = datetime.fromtimestamp(int(expires), tz=UTC)
    if expires_at <= now:
        return None
    return CsrfClaims(context=context, context_id=context_id, expires_at=expires_at)
