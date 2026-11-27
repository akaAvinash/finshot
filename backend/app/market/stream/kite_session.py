"""Operator command: turn a Kite login into the daily access token file.

Run on the server, where KITE_API_KEY, KITE_API_SECRET and
KITE_ACCESS_TOKEN_FILE are set:

    python -m app.market.stream.kite_session login-url
    python -m app.market.stream.kite_session exchange

`login-url` prints the Kite login page for the configured app. After you
sign in, Kite redirects to the app's registered redirect URL with a
`request_token` in the query string. `exchange` asks for that token without
echoing it, exchanges it for an access token (POST /session/token), and
writes the token to KITE_ACCESS_TOKEN_FILE (mode 0600, atomic replace). The
running stream picks it up on its next connection. Nothing secret is
printed or logged. Kite access tokens expire every day around 06:00 IST."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import httpx

from app.core.config import Settings
from app.market.stream.kite import API_ROOT


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    return hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()


def write_token_file(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".kite-token-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(token)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def exchange(settings: Settings, request_token: str, client: httpx.Client | None = None) -> None:
    if not (settings.kite_api_key and settings.kite_api_secret and settings.kite_access_token_file):
        raise SystemExit("KITE_API_KEY, KITE_API_SECRET and KITE_ACCESS_TOKEN_FILE must be set")
    key = settings.kite_api_key.get_secret_value()
    secret = settings.kite_api_secret.get_secret_value()
    http = client or httpx.Client(timeout=15.0)
    try:
        response = http.post(
            f"{API_ROOT}/session/token",
            headers={"X-Kite-Version": "3"},
            data={
                "api_key": key,
                "request_token": request_token.strip(),
                "checksum": checksum(key, request_token.strip(), secret),
            },
        )
    finally:
        if client is None:
            http.close()
    if response.status_code != 200:
        raise SystemExit(f"Kite refused the exchange (HTTP {response.status_code}).")
    try:
        token = response.json()["data"]["access_token"]
    except (ValueError, KeyError, TypeError):
        raise SystemExit("Kite returned an unexpected response.") from None
    if not isinstance(token, str) or not token:
        raise SystemExit("Kite returned no access token.")
    write_token_file(Path(settings.kite_access_token_file), token)
    print("Access token saved. The market stream uses it on its next connection.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.market.stream.kite_session")
    parser.add_argument("command", choices=["login-url", "exchange"])
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "login-url":
        if not settings.kite_api_key:
            raise SystemExit("KITE_API_KEY must be set")
        key = settings.kite_api_key.get_secret_value()
        print(f"https://kite.zerodha.com/connect/login?v=3&api_key={key}")
        return 0
    request_token = getpass.getpass("request_token (input hidden): ")
    if not request_token.strip():
        raise SystemExit("No request_token given.")
    exchange(settings, request_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
