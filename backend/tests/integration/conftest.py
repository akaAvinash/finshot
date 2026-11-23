"""Fixtures for tests that need real PostgreSQL and Redis.

    TEST_DATABASE_URL=postgresql+asyncpg://user:pw@localhost:5432/tradeo_test
    TEST_REDIS_URL=redis://localhost:6379/15 pytest

These tests TRUNCATE the auth tables and FLUSHDB the Redis database. Point them
at throwaway instances."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import redis as redis_sync
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import SettingsFactory
from tests.support import Browser, FakeClock, FixedOtpProvider, db_rows

DB_URL = os.environ.get("TEST_DATABASE_URL")
REDIS_URL = os.environ.get("TEST_REDIS_URL")
BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _require_services() -> None:
    if not (DB_URL and REDIS_URL):
        pytest.skip("TEST_DATABASE_URL/TEST_REDIS_URL unset")


@pytest.fixture(autouse=True)
def clean_state(_require_services: None) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = DB_URL
    command.upgrade(cfg, "head")
    db_rows(DB_URL or "", "TRUNCATE audit_events, sessions, otp_challenges, users CASCADE")
    redis_sync.Redis.from_url(REDIS_URL or "").flushdb()


@pytest.fixture
def db_url() -> str:
    assert DB_URL
    return DB_URL


@pytest.fixture
def provider() -> FixedOtpProvider:
    return FixedOtpProvider()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_app(
    make_settings: SettingsFactory, provider: FixedOtpProvider, clock: FakeClock
) -> Iterator[Callable[..., TestClient]]:
    """Factory for a running app (own lifespan) over the real Postgres and Redis."""
    clients: list[TestClient] = []

    def make(**overrides: Any) -> TestClient:
        overrides.setdefault("otp_resend_cooldown_seconds", 0)
        settings: Settings = make_settings(database_url=DB_URL, redis_url=REDIS_URL, **overrides)
        client = TestClient(
            create_app(settings, otp_provider=provider, clock=clock),
            base_url="https://testserver",
        )
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in reversed(clients):
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_app: Callable[..., TestClient]) -> TestClient:
    return make_app()


@pytest.fixture
def browser(client: TestClient) -> Browser:
    return Browser(client)
