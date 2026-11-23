from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings
from tests.conftest import SettingsFactory

PROD_DB = "postgresql+asyncpg://tradeo:s3cret@db.internal:5432/tradeo"
PROD_REDIS = "rediss://:s3cret@cache.internal:6380/0"


def prod_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": PROD_DB,
        "redis_url": PROD_REDIS,
        "allowed_hosts": ["api.tradeo.example"],
        "cors_allowed_origins": ["https://app.tradeo.example"],
    }
    values.update(overrides)
    return values


def test_defaults_are_safe(make_settings: SettingsFactory) -> None:
    settings = make_settings(app_env="development")
    assert settings.app_env is Environment.DEVELOPMENT
    assert settings.cors_allowed_origins == []
    assert settings.log_format == "json"
    assert settings.show_docs is True


def test_database_and_redis_urls_are_required() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)  # type: ignore[call-arg]
    missing = {err["loc"][0] for err in exc.value.errors()}
    assert {"database_url", "redis_url"} <= missing


def test_rejects_non_asyncpg_database_url(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+asyncpg"):
        make_settings(database_url="postgresql://u:p@localhost/db")


def test_rejects_non_postgres_database_url(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError):
        make_settings(database_url="mysql://u:p@localhost/db")


def test_reads_comma_separated_lists_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com, localhost")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,https://app.example.com")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.allowed_hosts == ["api.example.com", "localhost"]
    assert settings.cors_allowed_origins == ["http://localhost:3000", "https://app.example.com"]


@pytest.mark.parametrize("origin", ["localhost:3000", "https://app.example.com/", "ftp://x"])
def test_rejects_malformed_cors_origin(make_settings: SettingsFactory, origin: str) -> None:
    with pytest.raises(ValidationError, match="CORS origin"):
        make_settings(cors_allowed_origins=[origin])


def test_valid_production_config_passes() -> None:
    settings = Settings(_env_file=None, **prod_values())  # type: ignore[arg-type]
    assert settings.show_docs is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"cors_allowed_origins": ["*"]}, "must not contain '\\*'"),
        ({"cors_allowed_origins": ["http://app.example.com"]}, "must use https"),
        ({"allowed_hosts": ["*"]}, "ALLOWED_HOSTS"),
        ({"docs_enabled": True}, "DOCS_ENABLED"),
        ({"log_format": "console"}, "LOG_FORMAT"),
        ({"log_level": "DEBUG"}, "LOG_LEVEL"),
        ({"database_url": "postgresql+asyncpg://tradeo@db:5432/tradeo"}, "DATABASE_URL"),
        ({"redis_url": "redis://cache:6379/0"}, "REDIS_URL"),
    ],
)
def test_production_rejects_unsafe_settings(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **prod_values(**overrides))  # type: ignore[arg-type]


def test_staging_gets_the_same_rules() -> None:
    with pytest.raises(ValidationError, match="unsafe staging"):
        Settings(_env_file=None, **prod_values(app_env="staging", docs_enabled=True))  # type: ignore[arg-type]


def test_development_allows_wildcard_cors(make_settings: SettingsFactory) -> None:
    assert make_settings(
        app_env="development", cors_allowed_origins=["*"]
    ).cors_allowed_origins == ["*"]
