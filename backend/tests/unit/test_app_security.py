from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import SettingsFactory


def test_generates_request_id(client: TestClient) -> None:
    response = client.get("/health/live")
    assert len(response.headers["X-Request-ID"]) == 32


def test_echoes_well_formed_request_id(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "abc-123_x.y"})
    assert response.headers["X-Request-ID"] == "abc-123_x.y"


@pytest.mark.parametrize("bad", ["has space", "x" * 65, "injecté", "a;b"])
def test_replaces_malformed_request_id(client: TestClient, bad: str) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": bad.encode("utf-8")})
    assert response.headers["X-Request-ID"] != bad
    assert len(response.headers["X-Request-ID"]) == 32


def test_security_headers(client: TestClient) -> None:
    headers = client.get("/health/live").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Cache-Control"] == "no-store"
    assert headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert "Strict-Transport-Security" not in headers


def test_hsts_only_in_production(make_settings: SettingsFactory) -> None:
    settings = make_settings(
        app_env="production",
        database_url="postgresql+asyncpg://u:pw@db/tradeo",
        redis_url="redis://:pw@cache:6379/0",
        allowed_hosts=["testserver"],
    )
    with TestClient(create_app(settings)) as client:
        headers = client.get("/health/live").headers
    assert headers["Strict-Transport-Security"].startswith("max-age=")


def test_rejects_unknown_host(client: TestClient) -> None:
    response = client.get("/openapi.json", headers={"Host": "evil.example"})
    assert response.status_code == 400


def test_health_probes_skip_host_check(client: TestClient) -> None:
    """Container/orchestrator probes call the raw IP, which is not an allowed host."""
    assert client.get("/health/live", headers={"Host": "10.0.0.7:8000"}).status_code == 200
    assert client.get("/health/ready", headers={"Host": "10.0.0.7:8000"}).status_code == 503


def test_docs_disabled_in_production(make_settings: SettingsFactory) -> None:
    settings = make_settings(
        app_env="production",
        database_url="postgresql+asyncpg://u:pw@db/tradeo",
        redis_url="redis://:pw@cache:6379/0",
        allowed_hosts=["testserver"],
    )
    with TestClient(create_app(settings)) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404


def test_docs_enabled_in_development(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_cors_disabled_by_default(client: TestClient) -> None:
    response = client.get("/health/live", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_only_listed_origins(make_settings: SettingsFactory) -> None:
    app = create_app(make_settings(cors_allowed_origins=["http://localhost:3000"]))
    with TestClient(app) as client:
        allowed = client.get("/health/live", headers={"Origin": "http://localhost:3000"})
        denied = client.get("/health/live", headers={"Origin": "https://evil.example"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers


def test_unhandled_errors_return_generic_500(make_settings: SettingsFactory) -> None:
    app = create_app(make_settings())

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom", headers={"X-Request-ID": "req-1"})
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Internal server error",
            "request_id": "req-1",
        }
    }
    assert "hunter2" not in response.text


def test_no_order_routes_exist(client: TestClient) -> None:
    """Live order placement is out of scope for this foundation."""
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "order" in p.lower()]
    assert set(paths) == {"/health/live", "/health/ready"}


def test_access_log_is_json_with_request_id(
    capsys: pytest.CaptureFixture[str], client: TestClient
) -> None:
    capsys.readouterr()
    client.get("/health/live", headers={"X-Request-ID": "log-check-1"})
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    access = [line for line in lines if line.get("event") == "request"]
    assert access, lines
    entry = access[-1]
    assert entry["request_id"] == "log-check-1"
    assert entry["path"] == "/health/live"
    assert entry["status"] == 200
    assert entry["level"] == "info"
    assert "timestamp" in entry
