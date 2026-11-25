"""Read-only smoke check for a Tradeo staging API (TRAD-6, T03).

Standard library only. Makes GET requests only. Prints status codes and the
shape of each response (top-level keys, counts, the `source` label), never
response values such as balances, and never the session cookie.

Usage. STAGING_BASE_URL must reach the API itself. On staging the public
https origin serves only the frontend, which proxies just a few API paths, and
the API publishes no host port. So run it inside the API container, feeding the
script on stdin (see backend/docs/STAGING_HANDOFF.md for the full command):

    docker compose --project-name tradeo-staging -f compose.yaml exec -T \
        -e STAGING_BASE_URL=http://127.0.0.1:8000 -e STAGING_SESSION_COOKIE \
        api python - < verify_staging.py

Any https:// origin that routes /api and /health to the API also works. Plain
http is accepted only for a loopback host.

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
import urllib.parse
import urllib.request

SESSION_COOKIE_NAME = "__Host-tradeo_session"
TIMEOUT_SECONDS = 15


def fetch(base: str, path: str, cookie: str | None) -> tuple[int, object | None]:
    request = urllib.request.Request(base + path, method="GET")  # noqa: S310 (main() enforces https)
    request.add_header("Accept", "application/json")
    if cookie:
        request.add_header("Cookie", f"{SESSION_COOKIE_NAME}={cookie}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
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
    parts = urllib.parse.urlsplit(base)
    loopback = parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")
    if not (parts.scheme == "https" and parts.hostname) and not loopback:
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
        ok = status == expected and (key is None or (isinstance(body, dict) and key in body))
        if path == "/api/v1/market/overview" and ok:
            ok = isinstance(body, dict) and body.get("source") == "demo"
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {path}  http={status}  {shape(body)}")
    print(f"\n{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
