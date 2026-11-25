"""Read-only smoke check for a Tradeo staging API (TRAD-6, T03).

Standard library only. Makes GET requests only. Prints status codes and the
shape of each response (top-level keys, counts, the `source` label), never
response values such as balances, and never the session cookie.

Usage. STAGING_BASE_URL must reach the API itself. On staging the public
https origin serves only the frontend, which proxies just a few API paths, so
run this on the staging host against the API container (http://127.0.0.1:<port>,
loopback only), or against an origin that routes /api and /health to the API:

    STAGING_BASE_URL=https://<api-origin-or-http://127.0.0.1:<port>> \
    STAGING_SESSION_COOKIE=<value of __Host-tradeo_session> \
    python backend/scripts/verify_staging.py

Without STAGING_SESSION_COOKIE only the unauthenticated checks run. The
cookie value comes from a normal sign-in (email code, then authenticator) and
stays in the environment: do not paste it into chat, Git or Jira.

Exit code 0 when every check that ran passed, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

SESSION_COOKIE_NAME = "__Host-tradeo_session"
TIMEOUT_SECONDS = 15


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return redirects to the caller as HTTP errors instead of following them.

    Following one would copy the session cookie to whatever host (or plain
    http) the Location header names.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def fetch(base: str, path: str, cookie: str | None) -> tuple[int, object | None]:
    request = urllib.request.Request(base + path, method="GET")  # noqa: S310 (main() enforces https)
    request.add_header("Accept", "application/json")
    if cookie:
        request.add_header("Cookie", f"{SESSION_COOKIE_NAME}={cookie}")
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, {"error": type(exc).__name__}
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


def shape(body: object | None) -> str:
    if not isinstance(body, dict):
        return "no JSON object"
    parts = [f"keys={sorted(body)}"]
    if "source" in body:
        parts.append(f"source={body['source']}")
    if "status" in body:
        parts.append(f"status={body['status']}")
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    for key, value in data.items():
        if isinstance(value, list):
            parts.append(f"{key}[]={len(value)}")
    return " ".join(parts)


def passes(status: int, body: object | None, expected: int, key: str | None) -> bool:
    """A check passes on the expected status and a JSON object body.

    An HTML fallback page, an empty body or JSON null is never a pass, even
    for endpoints with no required key.
    """
    if status != expected or not isinstance(body, dict):
        return False
    return key is None or key in body


# (path, needs session, expected status, required top-level key or None)
CHECKS = [
    ("/health/live", False, 200, "status"),
    ("/health/ready", False, 200, "checks"),
    ("/api/v1/market/overview", False, 200, "quotes"),
    ("/api/v1/market/instruments", False, 200, "instruments"),
    ("/api/v1/auth/me", True, 200, None),
    ("/api/v1/brokers/preview", True, 200, None),
    ("/api/v1/strategies/preview", True, 200, None),
    ("/api/v1/auto-trading/paper", True, 200, None),
    ("/api/v1/reports/paper", True, 200, "status"),
    ("/api/v1/alerts", True, 200, None),
]


def main() -> int:
    base = os.environ.get("STAGING_BASE_URL", "").rstrip("/")
    loopback = base.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]"))
    if not (base.startswith("https://") or loopback):
        print(
            "Set STAGING_BASE_URL to an https:// origin or an http://127.0.0.1 address.",
            file=sys.stderr,
        )
        return 2
    cookie = os.environ.get("STAGING_SESSION_COOKIE") or None
    failed = 0
    for path, needs_session, expected, key in CHECKS:
        if needs_session and not cookie:
            print(f"SKIP  {path}  (no session cookie)")
            continue
        status, body = fetch(base, path, cookie if needs_session else None)
        ok = passes(status, body, expected, key)
        if path == "/api/v1/market/overview" and ok:
            ok = body.get("source") == "demo"
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {path}  http={status}  {shape(body)}")
    print(f"\n{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
