"""verify_staging.py: redirects never carry the cookie, and a 200 must be JSON."""

from __future__ import annotations

import importlib.util
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_staging.py"
spec = importlib.util.spec_from_file_location("verify_staging", SCRIPT)
assert spec and spec.loader
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def _serve(handler: type[BaseHTTPRequestHandler]) -> Iterator[HTTPServer]:
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def second_origin() -> Iterator[tuple[HTTPServer, list[str | None]]]:
    seen: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(self.headers.get("Cookie"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *args: object) -> None:
            pass

    for server in _serve(Handler):
        yield server, seen


def test_redirect_is_a_failure_and_the_cookie_is_not_forwarded(
    second_origin: tuple[HTTPServer, list[str | None]],
) -> None:
    target, seen = second_origin
    target_url = f"http://127.0.0.1:{target.server_port}/landing"

    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", target_url)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    for first in _serve(Redirector):
        status, _ = verify.fetch(f"http://127.0.0.1:{first.server_port}", "/x", "secret-cookie")
    assert status == 302
    assert seen == []


def test_cookie_is_sent_to_the_origin_itself(
    second_origin: tuple[HTTPServer, list[str | None]],
) -> None:
    server, seen = second_origin
    status, body = verify.fetch(f"http://127.0.0.1:{server.server_port}", "/x", "abc")
    assert (status, body) == (200, {"status": "ok"})
    assert seen == ["__Host-tradeo_session=abc"]


@pytest.mark.parametrize("body", [None, [], "<html>", 7])
def test_non_object_bodies_never_pass(body: object) -> None:
    assert verify.passes(200, body, 200, None) is False
    assert verify.passes(200, body, 200, "status") is False


def test_object_bodies_pass_and_status_still_matters() -> None:
    assert verify.passes(200, {}, 200, None) is True
    assert verify.passes(200, {"status": "ok"}, 200, "status") is True
    assert verify.passes(200, {"other": 1}, 200, "status") is False
    assert verify.passes(404, {"status": "ok"}, 200, "status") is False


def test_html_empty_and_null_responses_from_a_server_fail() -> None:
    for payload in (b"<html>fallback</html>", b"", b"null"):

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self, payload: bytes = payload) -> None:  # type: ignore[misc]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args: object) -> None:
                pass

        for server in _serve(Handler):
            status, body = verify.fetch(f"http://127.0.0.1:{server.server_port}", "/x", None)
        assert status == 200
        assert verify.passes(status, body, 200, None) is False


@pytest.mark.parametrize(
    "base",
    [
        "http://127.0.0.1.example.com",
        "http://localhost.example.com",
        "http://example.com",
        "ftp://127.0.0.1",
        "",
    ],
)
def test_base_url_must_be_https_or_a_real_loopback_host(
    monkeypatch: pytest.MonkeyPatch, base: str
) -> None:
    monkeypatch.setenv("STAGING_BASE_URL", base)
    assert verify.main() == 2
