from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

# Port 1 on localhost refuses connections immediately: "dependency down".
UNREACHABLE_DB = "postgresql+asyncpg://tradeo:pw@127.0.0.1:1/tradeo"
UNREACHABLE_REDIS = "redis://:pw@127.0.0.1:1/0"

TEST_SECRET = "test-secret-0123456789abcdef0123456789abcdef"

_ENV_KEYS = [
    "APP_ENV",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "DATABASE_URL",
    "REDIS_URL",
    "ALLOWED_HOSTS",
    "CORS_ALLOWED_ORIGINS",
    "DOCS_ENABLED",
    "HEALTH_CHECK_TIMEOUT_SECONDS",
    "AUTH_SECRET_KEY",
    "PUBLIC_ORIGIN",
    "OTP_PROVIDER",
    "TRUSTED_PROXY_HOPS",
    "MARKET_DATA_PROVIDER",
    "MARKET_DATA_TIMEOUT_SECONDS",
    "BROKER_PROVIDER",
    "BROKER_TIMEOUT_SECONDS",
    "STRATEGIES_ENABLED",
    "BACKTESTS_ENABLED",
    "BACKTEST_WORKER_ENABLED",
    "BACKTEST_WORKER_POLL_SECONDS",
    "BACKTEST_STALE_AFTER_SECONDS",
    "PAPER_ENABLED",
    "PAPER_WORKER_ENABLED",
    "PAPER_TICK_SECONDS",
    "PAPER_WORKER_POLL_SECONDS",
]


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings match environment names case-insensitively, so clear any casing.
    wanted = {key.upper() for key in _ENV_KEYS}
    for name in list(os.environ):
        if name.upper() in wanted:
            monkeypatch.delenv(name, raising=False)


SettingsFactory = Callable[..., Settings]


@pytest.fixture
def make_settings() -> SettingsFactory:
    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "app_env": "test",
            "database_url": UNREACHABLE_DB,
            "redis_url": UNREACHABLE_REDIS,
            "allowed_hosts": ["testserver", "localhost"],
            "health_check_timeout_seconds": 1.0,
            "auth_secret_key": TEST_SECRET,
            "public_origin": "https://testserver",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return factory


@pytest.fixture
def client(make_settings: SettingsFactory) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client
