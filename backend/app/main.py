"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.router import api_router
from app.api.routes import health
from app.auth.crypto import Keys
from app.auth.otp import ConsoleOtpProvider, DisabledOtpProvider, OtpProvider
from app.auth.ratelimit import RateLimiter
from app.auth.service import AuthService, Clock, utc_now
from app.brokers.adapter import BrokerAdapter, DemoBrokerAdapter
from app.brokers.service import BrokerService
from app.cache.redis import create_redis
from app.core.config import Environment, Settings, get_settings
from app.core.errors import ApiError, error_response
from app.core.logging import configure_logging
from app.core.middleware import (
    HostAllowlistMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.db.session import create_engine, create_session_factory
from app.market.demo import DemoMarketDataProvider
from app.market.provider import DisabledMarketDataProvider, MarketDataProvider
from app.strategies.service import StrategyService

logger = structlog.get_logger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    otp_provider: OtpProvider | None = None,
    clock: Clock = utc_now,
    market_provider: MarketDataProvider | None = None,
    broker_adapter: BrokerAdapter | None = None,
) -> FastAPI:
    """`otp_provider`, `clock`, `market_provider` and `broker_adapter` are
    injection points for tests. Production wiring picks the OTP provider from
    OTP_PROVIDER, the market data provider from MARKET_DATA_PROVIDER and the
    broker adapter from BROKER_PROVIDER (an injected adapter is ignored when
    BROKER_PROVIDER=disabled)."""
    settings = settings or get_settings()
    configure_logging(settings)
    provider: OtpProvider = otp_provider or (
        ConsoleOtpProvider() if settings.otp_provider == "console" else DisabledOtpProvider()
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Engine and Redis client connect lazily, so startup does not fail if a
        # dependency is briefly down; /health/ready reports that instead.
        app.state.db_engine = create_engine(settings)
        app.state.session_factory = create_session_factory(app.state.db_engine)
        app.state.redis = create_redis(settings)
        keys = Keys.from_secret(settings.auth_secret_key.get_secret_value())
        app.state.auth = AuthService(
            settings=settings,
            session_factory=app.state.session_factory,
            limiter=RateLimiter(app.state.redis, keys),
            provider=provider,
            keys=keys,
            clock=clock,
        )
        app.state.brokers = BrokerService(
            session_factory=app.state.session_factory,
            adapter=(
                (broker_adapter or DemoBrokerAdapter())
                if settings.broker_provider == "demo"
                else None
            ),
            clock=clock,
            timeout_seconds=settings.broker_timeout_seconds,
        )
        app.state.strategies = StrategyService(
            session_factory=app.state.session_factory,
            clock=clock,
            enabled=settings.strategies_enabled,
        )
        logger.info("startup", env=settings.app_env.value, version=__version__)
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.db_engine.dispose()
            logger.info("shutdown")

    docs = settings.show_docs
    app = FastAPI(
        title="Tradeo API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.market_provider = market_provider or (
        DemoMarketDataProvider()
        if settings.market_data_provider == "demo"
        else DisabledMarketDataProvider()
    )

    # Error bodies follow the contract's error shape in contracts/openapi.yaml
    # ({"code": UPPER_SNAKE, "message": str}). requestId is an extra field the
    # contract permits, so clients can quote it when reporting a problem.
    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(
            request,
            exc.status_code,
            exc.code,
            exc.message,
            retry_after_seconds=exc.retry_after_seconds,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # The contract uses 400 INVALID_REQUEST, not FastAPI's default 422.
        return error_response(
            request, 400, "INVALID_REQUEST", "The request parameters are invalid."
        )

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        # Log the traceback; never return it to the client.
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        return error_response(request, 500, "INTERNAL_ERROR", "Internal server error")

    app.include_router(health.router)
    app.include_router(api_router)

    # Middleware runs outermost-last-added. Order (outer -> inner):
    # RequestContext -> SecurityHeaders -> HostAllowlist -> CORS -> app
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
            max_age=600,
        )
    app.add_middleware(HostAllowlistMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.app_env == Environment.PRODUCTION)
    app.add_middleware(RequestContextMiddleware)

    return app
