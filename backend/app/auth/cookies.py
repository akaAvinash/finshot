"""Cookie names and helpers.

Both cookies are host-only (no Domain), HttpOnly, Secure, SameSite=Lax, Path=/.
The __Host- prefix makes browsers enforce that. Each cookie is its own
Set-Cookie header field; fields are never combined."""

from __future__ import annotations

from starlette.responses import Response

SESSION_COOKIE = "__Host-tradeo_session"
CSRF_COOKIE = "__Host-tradeo_csrf"


def set_cookie(response: Response, name: str, value: str) -> None:
    # No max_age/expires: browser-session cookies. Expiry is enforced server-side.
    response.set_cookie(
        name, value, path="/", secure=True, httponly=True, samesite="lax", domain=None
    )


def clear_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")
