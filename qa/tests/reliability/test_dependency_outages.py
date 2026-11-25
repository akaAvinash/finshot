"""Fail-closed behaviour when PostgreSQL or Redis disappears, and recovery afterwards.

Each test starts a private backend whose DATABASE_URL or REDIS_URL goes through
a TCP fault proxy, so cutting it affects only that backend.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse, urlunparse

import pytest

from qa.core.actors import Person
from qa.core.client import ApiClient
from qa.core.faults import TcpProxy

pytestmark = [pytest.mark.needs_services, pytest.mark.outage, pytest.mark.suite("reliability")]

# During an outage each request uses its own connection: the backend closes a
# keep-alive connection after an unhandled error (see test_500_* below), and
# these tests are about the status code, not connection reuse.
CLOSE = {"Connection": "close"}


def _via_proxy(url: str, proxy: TcpProxy) -> str:
    p = urlparse(url)
    netloc = p.netloc.rsplit("@", 1)
    host = f"127.0.0.1:{proxy.port}"
    netloc = f"{netloc[0]}@{host}" if len(netloc) == 2 else host
    return urlunparse(p._replace(netloc=netloc))


def _proxy_for(url: str) -> TcpProxy:
    p = urlparse(url)
    default = 5432 if p.scheme.startswith("postgres") else 6379
    proxy = TcpProxy(p.hostname or "127.0.0.1", p.port or default)
    proxy.start()
    return proxy


@pytest.fixture
def redis_proxy(services):
    proxy = _proxy_for(services.redis_url)
    yield proxy
    proxy.stop()


@pytest.fixture
def db_proxy(services):
    proxy = _proxy_for(services.database_url)
    yield proxy
    proxy.stop()


@pytest.mark.severity("critical")
@pytest.mark.req("REL-AUTH-001")
def test_redis_outage_fails_closed_for_otp_and_login(backend_factory, services, sink, redis_proxy):
    b = backend_factory(
        "redis-outage",
        REDIS_URL=_via_proxy(services.redis_url, redis_proxy),
        REDIS_SOCKET_TIMEOUT_SECONDS="1",
        OTP_RESEND_COOLDOWN_SECONDS="0",
    )
    p = Person(b, sink)
    p.register_ready()
    c = ApiClient(b.base_url, name="during-outage", strict_contract=False)
    c.fetch_csrf()
    redis_proxy.cut()
    try:
        code, _ = p.device.fresh_code()
        r = c.post("/auth/login/totp", {"phone": p.phone, "code": code}, headers=CLOSE)
        assert r.status_code >= 500, (
            f"login must fail closed without Redis (rate limits unavailable), got {r.status_code}"
        )
        r = c.post("/auth/otp/request", {"phone": p.phone, "channel": "email"}, headers=CLOSE)
        assert r.status_code >= 500, f"OTP request must fail closed without Redis, got {r.status_code}"
        assert "redis" not in r.text.lower() and "Traceback" not in r.text, "no internals in the error body"
    finally:
        redis_proxy.restore()
    time.sleep(1.5)
    ok = ApiClient(b.base_url, name="after-recovery")
    ok.fetch_csrf()
    p.login_totp(ok)
    assert ok.get("/auth/me").status_code == 200, "service recovers once Redis is back"
    c.close()
    ok.close()


@pytest.mark.severity("critical")
@pytest.mark.req("REL-AUTH-002")
def test_database_outage_fails_closed_and_recovers(backend_factory, services, sink, db_proxy):
    b = backend_factory(
        "db-outage",
        DATABASE_URL=_via_proxy(services.database_url, db_proxy),
        DATABASE_POOL_TIMEOUT_SECONDS="2",
        OTP_RESEND_COOLDOWN_SECONDS="0",
    )
    p = Person(b, sink)
    signed_in = p.register_ready()
    signed_in.strict_contract = False
    db_proxy.cut()
    try:
        r = signed_in.get("/auth/me", headers=CLOSE)
        assert r.status_code >= 500, f"session check must not succeed without the database, got {r.status_code}"
        assert "postgres" not in r.text.lower() and "Traceback" not in r.text
        ready = signed_in.get("/health/ready", headers=CLOSE)
        assert ready.status_code == 503, "readiness must report the outage"
    finally:
        db_proxy.restore()
    deadline = time.time() + 20
    status = None
    while time.time() < deadline:
        status = signed_in.get("/auth/me", headers=CLOSE).status_code
        if status == 200:
            break
        time.sleep(0.5)
    assert status == 200, "the same session works again after the database returns"


@pytest.mark.severity("high")
@pytest.mark.req("REL-AUTH-003", "AUTH-OTP-008")
def test_email_delivery_failure_returns_503_without_details(people, anon, sink):
    p = people()
    p.invite()
    sink.fail_deliveries("554 5.7.1 QA-SECRET-REPLY-TEXT relay denied")
    anon.fetch_csrf()
    r = anon.post("/auth/otp/request", {"phone": p.phone, "channel": "email"})
    assert r.status_code == 503
    assert r.json()["code"] == "OTP_DELIVERY_UNAVAILABLE"
    assert "QA-SECRET-REPLY-TEXT" not in r.text, "SMTP server text must not reach the client"
    sink.fail_deliveries(None)
    r = anon.post("/auth/otp/request", {"phone": p.phone, "channel": "email"})
    assert r.status_code == 202, "delivery works again after the mail server recovers"


@pytest.mark.severity("low")
@pytest.mark.req("REL-HTTP-001", "SEC-HDR-001")
def test_500_responses_keep_request_id_and_security_headers(backend_factory, services, sink, redis_proxy):
    """An INTERNAL_ERROR answer should look like every other answer: the body's
    requestId matches an X-Request-ID header (contract AuthError.requestId) and
    the standard security headers are present. The keep-alive connection should
    stay usable for the next request."""
    b = backend_factory(
        "redis-500", REDIS_URL=_via_proxy(services.redis_url, redis_proxy), REDIS_SOCKET_TIMEOUT_SECONDS="1"
    )
    c = ApiClient(b.base_url, name="500-probe", strict_contract=False)
    c.fetch_csrf()
    reused = ApiClient(b.base_url, name="keepalive", strict_contract=False)
    reused.fetch_csrf()
    redis_proxy.cut()
    try:
        r = c.post("/auth/otp/request", {"phone": "+919811111111", "channel": "email"}, headers=CLOSE)
        assert r.status_code == 500 and r.json()["code"] == "INTERNAL_ERROR"
        problems = []
        if r.headers.get("x-request-id") != r.json().get("requestId"):
            problems.append("X-Request-ID header missing or different from body requestId")
        for h in ("x-content-type-options", "cache-control", "content-security-policy"):
            if h not in r.headers:
                problems.append(f"missing {h}")
        statuses = []
        for _ in range(2):
            try:
                statuses.append(
                    reused.post("/auth/otp/request", {"phone": "+919811111111", "channel": "email"}).status_code
                )
            except Exception as exc:  # noqa: BLE001 - recording transport failures is the point
                statuses.append(type(exc).__name__)
        if any(not isinstance(s, int) for s in statuses):
            problems.append(f"keep-alive connection dropped after a 500: {statuses}")
        assert not problems, "; ".join(problems)
    finally:
        redis_proxy.restore()
        c.close()
