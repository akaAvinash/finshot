"""Application settings, loaded from environment variables and validated at startup.

The service refuses to start on invalid or unsafe configuration instead of
falling back to permissive defaults.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator, model_validator
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

    # --- Authentication (Phase A) -------------------------------------------
    # Master secret for HMAC keys (OTP digests, session digests, CSRF tokens).
    # Required, no default. Generate with: openssl rand -hex 32
    auth_secret_key: SecretStr = Field(min_length=32)
    # The browser-facing origin of the web app, e.g. https://app.example.com.
    # Used for the Origin check on state-changing requests.
    public_origin: str

    # "disabled": no SMS is sent, OTP requests return 503.
    # "console": development only; prints the code to an interactive terminal.
    # Real SMS providers arrive in a later phase.
    otp_provider: Literal["disabled", "console", "mock", "staging"] = "disabled"
    # Where email codes go. "smtp" is the only real provider; "mock" and
    # "staging" follow the same environment rules as the SMS ones.
    otp_email_provider: Literal["disabled", "mock", "staging", "smtp"] = "disabled"
    otp_ttl_seconds: int = Field(default=300, ge=30, le=300)
    otp_max_attempts: int = Field(default=5, ge=1, le=5)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=0, le=600)

    # Delivery spending limits, counted per UTC day in Redis. Only real
    # deliveries to invited numbers count. Over a limit, requests return 503.
    otp_daily_delivery_limit: int = Field(default=100, ge=1)
    otp_daily_delivery_limit_per_phone: int = Field(default=10, ge=1)
    # Staging provider: codes for allowlisted synthetic numbers go to this file
    # (mode 0600), never to logs or SMS. Read it on the server with
    # `python -m app.auth.admin staging-otp`.
    otp_staging_file: str | None = None
    otp_staging_allowlist: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # SMTP email delivery. Credentials come from the environment only.
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    # TOTP step-up: how long a proven code opens sensitive actions, and how
    # recent a sign-in must be to start enrolment.
    step_up_ttl_seconds: int = Field(default=600, ge=60, le=900)
    totp_enroll_recent_seconds: int = Field(default=900, ge=60, le=900)
    totp_pending_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    rate_limit_totp_per_user: int = Field(default=5, ge=1)
    rate_limit_totp_per_ip: int = Field(default=20, ge=1)
    rate_limit_totp_window_seconds: int = Field(default=900, ge=1)

    # Invite-only tester sign-in (demo and paper only). Off unless the owner
    # turns it on. A tester session lasts at most `tester_session_ttl_seconds`
    # (the contract says within two hours) and an invite code at most 15 minutes.
    tester_sign_in_enabled: bool = False
    tester_session_ttl_seconds: int = Field(default=7200, ge=300, le=7200)
    tester_invite_ttl_seconds: int = Field(default=900, ge=60, le=900)

    session_idle_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    session_absolute_ttl_seconds: int = Field(default=43_200, ge=300, le=2_592_000)
    csrf_pre_login_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)

    # Phone number change: requests and confirmations per account per window.
    rate_limit_phone_change_per_user: int = Field(default=5, ge=1)
    rate_limit_phone_change_verify_per_user: int = Field(default=10, ge=1)
    rate_limit_phone_change_window_seconds: int = Field(default=3600, ge=1)

    # Rate limits (fixed windows, counted in Redis). Exceeding one returns 429.
    rate_limit_otp_request_per_phone: int = Field(default=5, ge=1)
    rate_limit_otp_request_per_ip: int = Field(default=20, ge=1)
    rate_limit_otp_request_per_context: int = Field(default=5, ge=1)
    rate_limit_otp_request_window_seconds: int = Field(default=3600, ge=1)
    rate_limit_otp_verify_per_ip: int = Field(default=30, ge=1)
    rate_limit_otp_verify_window_seconds: int = Field(default=900, ge=1)
    rate_limit_csrf_per_ip: int = Field(default=60, ge=1)
    rate_limit_csrf_window_seconds: int = Field(default=60, ge=1)

    # How many reverse proxies sit in front of the API and append to
    # X-Forwarded-For. 0 trusts only the socket peer. Behind the Next.js
    # proxy set this to 1, otherwise every user shares one rate-limit bucket.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)

    # --- Market data (Phase B1, read-only) -------------------------------------
    # "demo": deterministic demo fixtures, labeled source=demo in responses.
    # "disabled": every market endpoint returns 503 MARKET_DATA_UNAVAILABLE.
    # Live feeds are a later phase.
    market_data_provider: Literal["demo", "disabled"] = "demo"
    market_data_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    # --- Brokers (Phase B2, demo only) -----------------------------------------
    # "demo": simulated, per-user connections with no provider requests.
    # "disabled": every broker endpoint returns 503 BROKER_UNAVAILABLE.
    # Live broker adapters need a separately approved phase.
    broker_provider: Literal["demo", "disabled"] = "demo"
    broker_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    # The app's own callback page a provider returns the browser to. A path on
    # the app's origin, never a full URL.
    broker_callback_path: str = Field(default="/brokers/callback", pattern=r"^/[A-Za-z0-9/_-]*$")

    # --- Strategies (Phase C1) -------------------------------------------------
    # false: every strategy endpoint returns 503 STRATEGY_UNAVAILABLE.
    strategies_enabled: bool = True

    # --- Backtests (Phase C2, demo candles only) -------------------------------
    # false: every backtest endpoint returns 503 BACKTEST_UNAVAILABLE and the
    # worker does not start.
    backtests_enabled: bool = True
    # The in-process worker that completes queued runs. Turn it off to run
    # the API without completing runs (tests drive the worker directly).
    backtest_worker_enabled: bool = True
    backtest_worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    # A run still `running` after this long is failed as abandoned.
    backtest_stale_after_seconds: int = Field(default=300, ge=10, le=3600)

    # --- Paper trading (Phase C3, demo candles, no broker) --------------------
    # false: both paper endpoints return 503 PAPER_UNAVAILABLE and the worker
    # does not start.
    paper_enabled: bool = True
    # The in-process worker that replays running paper engines. Turn it off to
    # run the API without ticks (tests drive the worker directly).
    paper_worker_enabled: bool = True
    # One demo session is replayed per running engine every tick.
    paper_tick_seconds: float = Field(default=3.0, ge=0.5, le=300)
    paper_worker_poll_seconds: float = Field(default=1.0, gt=0, le=60)

    # --- Reports (Phase D, paper ledger only) ---------------------------------
    # false: both report endpoints return 503 REPORTS_UNAVAILABLE.
    reports_enabled: bool = True

    # --- Advisory agents (Phase E1, deterministic, paper ledger only) ---------
    # false: every agent endpoint returns 503 AGENTS_UNAVAILABLE and the
    # worker does not start.
    agents_enabled: bool = True
    # The in-process worker that evaluates changed paper accounts. Turn it off
    # to run the API without evaluations (tests drive the worker directly).
    agent_worker_enabled: bool = True
    agent_worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    # An agent is `stale` when paper data it has not evaluated changed longer
    # ago than this.
    agent_stale_after_seconds: int = Field(default=30, ge=5, le=3600)

    # --- Alerts (Phase E2, in-app only) ---------------------------------------
    # false: every alert endpoint returns 503 ALERTS_UNAVAILABLE and the worker
    # does not start. Producers keep recording alerts, so none are lost.
    alerts_enabled: bool = True
    # The in-process worker that records broker-expiry and reconciliation
    # alerts. Turn it off to run the API without it (tests drive it directly).
    alert_worker_enabled: bool = True
    alert_worker_poll_seconds: float = Field(default=5.0, gt=0, le=300)

    # --- Alert delivery by email, SMS and push (contract 0.13.0) -------------
    # `log` is a simulated provider: it writes a masked log line and sends
    # nothing. It is refused in production. No real provider exists yet.
    notify_email_provider: Literal["disabled", "log"] = "disabled"
    notify_sms_provider: Literal["disabled", "log"] = "disabled"
    notify_push_provider: Literal["disabled", "log"] = "disabled"
    notify_worker_enabled: bool = True
    notify_worker_poll_seconds: float = Field(default=10.0, gt=0, le=300)
    # Alerts older than this when the worker first sees them are not sent.
    notify_lookback_seconds: int = Field(default=3600, ge=60, le=86_400)
    notify_daily_limit_per_channel: int = Field(default=20, ge=1, le=1000)
    notify_test_per_hour: int = Field(default=3, ge=1, le=60)

    # --- Data retention (contract 0.13.0) -------------------------------------
    # Bounds and default for the user's retention period, in days. The purge
    # worker runs every `retention_purge_interval_seconds` (the contract
    # promises at least once every 24 hours).
    data_retention_min_days: int = Field(default=30, ge=1, le=36500)
    data_retention_max_days: int = Field(default=730, ge=1, le=36500)
    data_retention_default_days: int = Field(default=365, ge=1, le=36500)
    retention_worker_enabled: bool = True
    retention_purge_interval_seconds: float = Field(default=3600.0, ge=60, le=86_400)

    @field_validator("otp_staging_allowlist", mode="before")
    @classmethod
    def _parse_allowlist(cls, value: object) -> object:
        return _split_csv(value)

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

    @field_validator("public_origin")
    @classmethod
    def _validate_public_origin(cls, value: str) -> str:
        message = "PUBLIC_ORIGIN must be scheme://host[:port] with no path, query or fragment"
        try:
            parts = urlsplit(value)
            parts.port  # noqa: B018 - raises ValueError on a malformed port
        except ValueError as exc:
            raise ValueError(message) from exc
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or "@" in parts.netloc
            or parts.path
            or parts.query
            or parts.fragment
            or "?" in value
            or "#" in value
        ):
            raise ValueError(message)
        # Canonical browser serialization: lowercase scheme and host, default port
        # dropped. The Origin header is compared to this string byte for byte.
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        default_port = 443 if parts.scheme == "https" else 80
        port = parts.port
        suffix = f":{port}" if port is not None and port != default_port else ""
        return f"{parts.scheme}://{host}{suffix}"

    @field_validator("auth_secret_key")
    @classmethod
    def _reject_placeholder_secret(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value().lower()
        if "change-me" in raw or "change_me" in raw or len(set(raw)) < 8:
            raise ValueError("AUTH_SECRET_KEY looks like a placeholder; generate a real secret")
        return value

    @model_validator(mode="after")
    def _enforce_retention_bounds(self) -> Self:
        if not (
            self.data_retention_min_days
            <= self.data_retention_default_days
            <= self.data_retention_max_days
        ):
            raise ValueError(
                "DATA_RETENTION_MIN_DAYS <= DATA_RETENTION_DEFAULT_DAYS <= DATA_RETENTION_MAX_DAYS"
            )
        return self

    @model_validator(mode="after")
    def _enforce_notify_provider_rules(self) -> Self:
        simulated = {
            self.notify_email_provider,
            self.notify_sms_provider,
            self.notify_push_provider,
        }
        if self.app_env == Environment.PRODUCTION and "log" in simulated:
            raise ValueError(
                "the simulated (log) notification provider is not allowed in production"
            )
        return self

    @model_validator(mode="after")
    def _enforce_otp_provider_rules(self) -> Self:
        # The console provider prints codes. It must never exist outside local dev.
        if self.otp_provider == "console" and self.app_env != Environment.DEVELOPMENT:
            raise ValueError("OTP_PROVIDER=console is only allowed when APP_ENV=development")
        # Mock and staging providers expose or fix codes. Production never uses
        # them, and nothing falls back to them: a misconfigured production
        # delivers nothing (HTTP 503).
        providers = {self.otp_provider, self.otp_email_provider}
        if self.app_env == Environment.PRODUCTION and providers & {"mock", "staging"}:
            raise ValueError("mock and staging OTP providers are not allowed in production")
        if "mock" in providers and self.app_env not in (Environment.DEVELOPMENT, Environment.TEST):
            raise ValueError("the mock OTP provider is only allowed in development and test")
        if "staging" in providers:
            if self.app_env == Environment.PRODUCTION:  # pragma: no cover - checked above
                raise ValueError("the staging OTP provider is not allowed in production")
            if not self.otp_staging_file or not self.otp_staging_allowlist:
                raise ValueError(
                    "the staging OTP provider needs OTP_STAGING_FILE and OTP_STAGING_ALLOWLIST"
                )
        if self.otp_email_provider == "smtp":
            missing = [
                name
                for name, value in (
                    ("SMTP_HOST", self.smtp_host),
                    ("SMTP_FROM", self.smtp_from),
                    ("SMTP_USERNAME", self.smtp_username),
                    ("SMTP_PASSWORD", self.smtp_password),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"OTP_EMAIL_PROVIDER=smtp needs {', '.join(missing)}")
            if not self.smtp_starttls and self.app_env.is_deployed:
                raise ValueError("SMTP_STARTTLS must stay on outside development")
        return self

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
        if not self.public_origin.startswith("https://"):
            problems.append("PUBLIC_ORIGIN must use https")
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
