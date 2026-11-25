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
        public_origin="https://testserver",
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
        public_origin="https://testserver",
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
        "code": "INTERNAL_ERROR",
        "message": "Internal server error",
        "requestId": "req-1",
    }
    assert "hunter2" not in response.text


def test_openapi_documents_400_not_422(client: TestClient) -> None:
    """Invalid requests return 400 INVALID_REQUEST, so no operation lists a 422."""
    document = client.get("/openapi.json").json()
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            assert "422" not in operation["responses"], (method, path)
    assert "HTTPValidationError" not in document["components"]["schemas"]
    command = document["paths"]["/api/v1/auto-trading/paper/commands"]["post"]
    assert set(command["responses"]) == {"200", "400", "401", "403", "409", "503"}
    for path in ("/api/v1/reports/paper", "/api/v1/reports/paper/trades.csv"):
        assert set(document["paths"][path]) == {"get"}, path  # reports are read-only
        assert set(document["paths"][path]["get"]["responses"]) == {"200", "400", "401", "503"}
    csv_ok = document["paths"]["/api/v1/reports/paper/trades.csv"]["get"]["responses"]["200"]
    assert set(csv_ok["content"]) == {"text/csv"}
    # Agents are read-only and advisory: GET only, no CSRF-protected writes.
    for path in ("/api/v1/agents", "/api/v1/agents/health"):
        assert set(document["paths"][path]) == {"get"}, path
        assert set(document["paths"][path]["get"]["responses"]) == {"200", "401", "503"}
    events = document["paths"]["/api/v1/agents/events"]
    assert set(events) == {"get"}
    assert set(events["get"]["responses"]) == {"200", "400", "401", "503"}


def test_no_order_routes_exist(client: TestClient) -> None:
    """Live order placement is out of scope for this foundation."""
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "order" in p.lower()]
    assert set(paths) == {
        "/health/live",
        "/health/ready",
        "/api/v1/auth/csrf",
        "/api/v1/auth/otp/request",
        "/api/v1/auth/otp/verify",
        "/api/v1/auth/login/totp",
        "/api/v1/auth/login/recovery",
        "/api/v1/auth/totp/recovery-codes",
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
        "/api/v1/auth/logout-all",
        "/api/v1/auth/sessions",
        "/api/v1/auth/sessions/{sessionId}",
        "/api/v1/settings/profile",
        "/api/v1/auth/totp/enroll",
        "/api/v1/auth/totp/confirm",
        "/api/v1/auth/totp/disable",
        "/api/v1/auth/step-up",
        "/api/v1/market/instruments",
        "/api/v1/market/overview",
        "/api/v1/market/instruments/{instrumentId}/candles",
        "/api/v1/brokers/preview",
        "/api/v1/brokers/preview/{provider}/actions",
        "/api/v1/strategies/preview",
        "/api/v1/strategies/preview/commands",
        "/api/v1/backtests/preview",
        "/api/v1/backtests/preview/runs",
        "/api/v1/backtests/preview/runs/{runId}",
        "/api/v1/auto-trading/paper",
        "/api/v1/auto-trading/paper/commands",
        "/api/v1/reports/paper",
        "/api/v1/reports/paper/trades.csv",
        "/api/v1/agents",
        "/api/v1/agents/health",
        "/api/v1/agents/events",
        "/api/v1/alerts",
        "/api/v1/alerts/{alertId}/ack",
        "/api/v1/alerts/preferences",
    }
    # Market data is read-only.
    for path, operations in paths.items():
        if path.startswith("/api/v1/market/"):
            assert set(operations) == {"get"}, path
    # Broker actions are limited to the four demo connection actions.
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    assert set(schema["BrokerActionRequest"]["properties"]["action"]["enum"]) == {
        "connect",
        "reconnect",
        "sync",
        "disconnect",
    }


def test_broker_adapter_protocol_is_read_only() -> None:
    """No order placement, modification or cancel method exists on the adapter."""
    from app.brokers.adapter import BrokerAdapter, DemoBrokerAdapter

    for cls in (BrokerAdapter, DemoBrokerAdapter):
        public = {name for name in vars(cls) if not name.startswith("_")}
        assert public == {"authorize", "fetch_account"}, cls


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


def test_validation_errors_use_contract_shape(make_settings: SettingsFactory) -> None:
    """contracts/openapi.yaml: bad parameters are 400 INVALID_REQUEST, not 422."""
    app = create_app(make_settings())

    @app.get("/needs-int")
    async def needs_int(limit: int) -> dict[str, int]:
        return {"limit": limit}

    with TestClient(app) as client:
        response = client.get("/needs-int?limit=abc", headers={"X-Request-ID": "req-2"})
    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "The request parameters are invalid.",
        "requestId": "req-2",
    }
