"""Pure-ASGI middleware: request IDs + access logging, and security headers."""

from __future__ import annotations

import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

access_logger = structlog.get_logger("tradeo.access")


class RequestContextMiddleware:
    """Assigns a request ID (or accepts a well-formed inbound one), binds it to
    the log context, echoes it on the response, and writes one access log line."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = (
            dict(scope["headers"]).get(REQUEST_ID_HEADER.lower().encode(), b"").decode("latin-1")
        )
        request_id = inbound if _VALID_REQUEST_ID.match(inbound) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            access_logger.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            # Context is left bound so the outer error handler can still log
            # with this request_id; it is cleared at the start of the next request.


class SecurityHeadersMiddleware:
    """Conservative headers for a JSON API. The interactive docs pages need
    inline scripts, so they get a looser CSP (and only exist outside prod)."""

    _API_CSP = "default-src 'none'; frame-ancestors 'none'"
    _DOCS_PATHS = ("/docs", "/redoc")

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_docs = scope["path"].startswith(self._DOCS_PATHS)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
                headers.setdefault("Cache-Control", "no-store")
                if not is_docs:
                    headers.setdefault("Content-Security-Policy", self._API_CSP)
                if self.hsts:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)


class HostAllowlistMiddleware(TrustedHostMiddleware):
    """Starlette's TrustedHostMiddleware, except /health/* is exempt.

    Container and orchestrator probes call the pod/container IP, which is not
    a public hostname. Health responses build no URLs and expose nothing
    sensitive, so skipping the Host check there is safe."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/health/"):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
