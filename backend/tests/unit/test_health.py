from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import health
from app.main import create_app
from tests.conftest import SettingsFactory


def test_live_is_ok_even_when_dependencies_are_down(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_503_when_dependencies_are_down(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "checks": {"database": "error", "redis": "error"},
    }


def test_ready_does_not_leak_connection_details(client: TestClient) -> None:
    body = client.get("/health/ready").text
    for secret_ish in ("127.0.0.1", "pw", "Connection", "refused"):
        assert secret_ish not in body


def test_ready_reports_each_dependency(
    make_settings: SettingsFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok(_: object) -> None:
        return None

    monkeypatch.setattr(health, "ping_database", ok)
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "redis": "error"}


def test_ready_is_ok_when_all_checks_pass(
    make_settings: SettingsFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok(_: object) -> None:
        return None

    monkeypatch.setattr(health, "ping_database", ok)
    monkeypatch.setattr(health, "ping_redis", ok)
    with TestClient(create_app(make_settings())) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


def test_ready_times_out_slow_dependencies(
    make_settings: SettingsFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    async def ok(_: object) -> None:
        return None

    async def hang(_: object) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(health, "ping_database", hang)
    monkeypatch.setattr(health, "ping_redis", ok)
    with TestClient(create_app(make_settings(health_check_timeout_seconds=0.1))) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "error"
