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
        "auth_secret_key": "prod-secret-9f8e7d6c5b4a39281706f5e4d3c2b1a0",
        "public_origin": "https://app.tradeo.example",
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
    monkeypatch.setenv("AUTH_SECRET_KEY", "env-secret-0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("PUBLIC_ORIGIN", "http://localhost:3000")
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
        ({"public_origin": "http://app.tradeo.example"}, "PUBLIC_ORIGIN must use https"),
        ({"otp_provider": "console"}, "only allowed when APP_ENV=development"),
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


def test_console_otp_provider_allowed_only_in_development(make_settings: SettingsFactory) -> None:
    assert make_settings(app_env="development", otp_provider="console").otp_provider == "console"
    with pytest.raises(ValidationError, match="only allowed when APP_ENV=development"):
        make_settings(app_env="test", otp_provider="console")


def test_otp_provider_defaults_to_disabled(make_settings: SettingsFactory) -> None:
    assert make_settings().otp_provider == "disabled"


@pytest.mark.parametrize(
    "secret",
    ["short", "change-me-change-me-change-me-change-me", "a" * 40, "CHANGE_ME_" + "x1" * 20],
)
def test_rejects_weak_or_placeholder_auth_secret(
    make_settings: SettingsFactory, secret: str
) -> None:
    with pytest.raises(ValidationError):
        make_settings(auth_secret_key=secret)


def test_auth_secret_is_required_and_hidden() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(
            _env_file=None, database_url="postgresql+asyncpg://u:p@h/db", redis_url="redis://h"
        )  # type: ignore[call-arg]
    missing = {err["loc"][0] for err in exc.value.errors()}
    assert {"auth_secret_key", "public_origin"} <= missing


def test_auth_secret_not_in_repr(make_settings: SettingsFactory) -> None:
    from tests.conftest import TEST_SECRET

    assert TEST_SECRET not in repr(make_settings())


def test_public_origin_accepts_explicit_port(make_settings: SettingsFactory) -> None:
    assert make_settings(public_origin="https://app.example.com:8443").public_origin.endswith(
        ":8443"
    )


@pytest.mark.parametrize(
    ("configured", "canonical"),
    [
        ("https://app.example.com:443", "https://app.example.com"),
        ("http://localhost:80", "http://localhost"),
        ("HTTPS://App.Example.COM", "https://app.example.com"),
        ("https://app.example.com:8443", "https://app.example.com:8443"),
        ("http://localhost:3000", "http://localhost:3000"),
    ],
)
def test_public_origin_is_normalized_to_browser_serialization(
    make_settings: SettingsFactory, configured: str, canonical: str
) -> None:
    from app.core.config import Environment

    settings = make_settings(public_origin=configured, app_env=Environment.TEST)
    assert settings.public_origin == canonical


@pytest.mark.parametrize(
    "origin",
    [
        "https://app.example.com/",
        "https://app.example.com/app",
        "https://app.example.com?x=1",
        "https://app.example.com#frag",
        "https://user:pw@app.example.com",
        "https://",
        "https:///path",
        "https://app.example.com:notaport",
        "app.example.com",
        "ftp://x",
    ],
)
def test_rejects_malformed_public_origin(make_settings: SettingsFactory, origin: str) -> None:
    with pytest.raises(ValidationError, match="PUBLIC_ORIGIN"):
        make_settings(public_origin=origin)


@pytest.mark.parametrize("override", [{"otp_ttl_seconds": 301}, {"otp_max_attempts": 6}])
def test_settings_cannot_exceed_contract_otp_limits(
    make_settings: SettingsFactory, override: dict[str, int]
) -> None:
    """The contract fixes OTP life at <= 5 minutes and <= 5 verify attempts."""
    with pytest.raises(ValidationError):
        make_settings(**override)


def test_retention_default_must_be_inside_bounds(make_settings: SettingsFactory) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_settings(data_retention_min_days=100, data_retention_default_days=50)
