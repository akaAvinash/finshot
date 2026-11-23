"""Application settings, loaded from environment variables and validated at startup.

The service refuses to start on invalid or unsafe configuration instead of
falling back to permissive defaults.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_deployed(self) -> bool:
        """Staging and production get the strict rules."""
        return self in (Environment.STAGING, Environment.PRODUCTION)


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # Validation errors must not echo DATABASE_URL/REDIS_URL credentials.
        hide_input_in_errors=True,
    )

    app_env: Environment = Environment.DEVELOPMENT
    app_name: str = "tradeo-api"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # Required: no default, so a missing value fails fast.
    database_url: PostgresDsn
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=5, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    database_statement_timeout_ms: int = Field(default=15_000, ge=100, le=600_000)

    redis_url: RedisDsn
    redis_socket_timeout_seconds: float = Field(default=2.0, gt=0, le=60)

    # Comma-separated in the environment, e.g. "api.example.com,localhost".
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"]
    )
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # None means "on outside staging/production".
    docs_enabled: bool | None = None

    health_check_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    @field_validator("allowed_hosts", "cors_allowed_origins", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg(cls, value: PostgresDsn) -> PostgresDsn:
        if value.scheme != "postgresql+asyncpg":
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// scheme")
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _validate_origins(cls, value: list[str]) -> list[str]:
        for origin in value:
            if origin == "*":
                continue  # rejected below for deployed environments
            if not origin.startswith(("http://", "https://")) or origin.endswith("/"):
                raise ValueError(
                    f"CORS origin {origin!r} must be a scheme://host[:port] with no trailing slash"
                )
        return value

    @model_validator(mode="after")
    def _enforce_deployed_rules(self) -> Self:
        if not self.app_env.is_deployed:
            return self

        problems: list[str] = []
        if "*" in self.cors_allowed_origins:
            problems.append("CORS_ALLOWED_ORIGINS must not contain '*'")
        if any("*" == host for host in self.allowed_hosts) or not self.allowed_hosts:
            problems.append("ALLOWED_HOSTS must list explicit hostnames")
        if self.docs_enabled:
            problems.append("DOCS_ENABLED must be false")
        if self.log_format != "json":
            problems.append("LOG_FORMAT must be json")
        if self.log_level == "DEBUG":
            problems.append("LOG_LEVEL must not be DEBUG")
        if not self.database_url.hosts()[0].get("password"):
            problems.append("DATABASE_URL must include a password")
        if not self.redis_url.password:
            problems.append("REDIS_URL must include a password")
        for origin in self.cors_allowed_origins:
            if origin.startswith("http://"):
                problems.append(f"CORS origin {origin!r} must use https")
        if problems:
            raise ValueError(f"unsafe {self.app_env.value} configuration: " + "; ".join(problems))
        return self

    @property
    def show_docs(self) -> bool:
        if self.docs_enabled is None:
            return not self.app_env.is_deployed
        return self.docs_enabled


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Required fields (DATABASE_URL, REDIS_URL) come from the environment.
    return Settings()
