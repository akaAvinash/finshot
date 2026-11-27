"""Application factory."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.agents.service import AgentService
from app.alerts.delivery import Channel, NotificationProvider, build_providers
from app.alerts.delivery_service import AlertDeliveryService
from app.alerts.service import AlertService
from app.api.router import api_router
from app.api.routes import health
from app.auth.crypto import Keys
from app.auth.otp import OtpProvider
from app.auth.phone_change import PhoneChangeService
from app.auth.providers import build_email_provider, build_sms_provider
from app.auth.ratelimit import RateLimiter
from app.auth.service import AuthService, Clock, utc_now
from app.auth.smtp import SmtpTransport
from app.auth.stepup import StepUpService
from app.backtests.service import BacktestService
from app.brokers.adapter import BrokerAdapter, DemoBrokerAdapter
from app.brokers.connections import BrokerConnectionService
from app.brokers.service import BrokerService
from app.cache.redis import create_redis
from app.core.config import Environment, Settings, get_settings
from app.core.errors import ApiError, error_response
from app.core.logging import configure_logging
from app.core.middleware import (
    HostAllowlistMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from app.db.session import create_engine, create_session_factory
from app.market.demo import DemoMarketDataProvider
from app.market.provider import DisabledMarketDataProvider, MarketDataProvider
from app.market.stream.hub import MarketStreamHub
from app.market.stream.source import MockTickSource, TickSource
from app.paper.service import PaperService
from app.reports.service import ReportService
from app.retention.service import RetentionService
from app.strategies.service import StrategyService

logger = structlog.get_logger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    otp_provider: OtpProvider | None = None,
    email_provider: OtpProvider | None = None,
    smtp_transport: SmtpTransport | None = None,
    clock: Clock = utc_now,
    market_provider: MarketDataProvider | None = None,
    broker_adapter: BrokerAdapter | None = None,
    notification_providers: dict[Channel, NotificationProvider] | None = None,
    market_stream_source: TickSource | None = None,
) -> FastAPI:
    """`otp_provider`, `clock`, `market_provider` and `broker_adapter` are
    injection points for tests. Production wiring picks the OTP provider from
    OTP_PROVIDER, the market data provider from MARKET_DATA_PROVIDER and the
    broker adapter from BROKER_PROVIDER (an injected adapter is ignored when
    BROKER_PROVIDER=disabled)."""
    settings = settings or get_settings()
    configure_logging(settings)
    provider: OtpProvider = otp_provider or build_sms_provider(settings)
    email: OtpProvider = email_provider or build_email_provider(settings, smtp_transport)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Engine and Redis client connect lazily, so startup does not fail if a
        # dependency is briefly down; /health/ready reports that instead.
        app.state.db_engine = create_engine(settings)
        app.state.session_factory = create_session_factory(app.state.db_engine)
        app.state.redis = create_redis(settings)
        keys = Keys.from_secret(settings.auth_secret_key.get_secret_value())
        app.state.stepup = StepUpService(
            settings=settings,
            session_factory=app.state.session_factory,
            limiter=RateLimiter(app.state.redis, keys),
            keys=keys,
            clock=clock,
        )
        app.state.auth = AuthService(
            settings=settings,
            session_factory=app.state.session_factory,
            limiter=RateLimiter(app.state.redis, keys),
            provider=provider,
            email_provider=email,
            keys=keys,
            clock=clock,
            stepup=app.state.stepup,
        )
        app.state.phone_change = PhoneChangeService(app.state.auth)
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
        app.state.broker_connections = BrokerConnectionService(
            session_factory=app.state.session_factory,
            adapter=app.state.brokers._adapter,
            clock=clock,
            timeout_seconds=settings.broker_timeout_seconds,
            callback_path=settings.broker_callback_path,
        )
        app.state.strategies = StrategyService(
            session_factory=app.state.session_factory,
            clock=clock,
            enabled=settings.strategies_enabled,
        )
        app.state.backtests = BacktestService(
            session_factory=app.state.session_factory,
            clock=clock,
            enabled=settings.backtests_enabled,
            stale_after_seconds=settings.backtest_stale_after_seconds,
        )
        app.state.paper = PaperService(
            session_factory=app.state.session_factory,
            clock=clock,
            enabled=settings.paper_enabled,
            tick_seconds=settings.paper_tick_seconds,
        )
        app.state.reports = ReportService(
            session_factory=app.state.session_factory,
            clock=clock,
            enabled=settings.reports_enabled,
        )
        app.state.agents = AgentService(
            session_factory=app.state.session_factory,
            clock=clock,
            enabled=settings.agents_enabled,
            stale_after_seconds=settings.agent_stale_after_seconds,
        )
        app.state.alert_delivery = AlertDeliveryService(
            settings=settings,
            session_factory=app.state.session_factory,
            clock=clock,
            providers=notification_providers or build_providers(settings),
        )
        app.state.alerts = AlertService(
            session_factory=app.state.session_factory,
            clock=clock,
            enabled=settings.alerts_enabled,
            delivery=app.state.alert_delivery,
        )
        app.state.retention = RetentionService(
            settings=settings, session_factory=app.state.session_factory, clock=clock
        )
        workers: list[asyncio.Task[None]] = []
        app.state.market_stream = None
        if settings.market_stream_enabled:
            app.state.market_stream = MarketStreamHub(
                market_stream_source or _build_stream_source(settings, clock),
                clock=clock,
                queue_size=settings.market_stream_queue_size,
                stale_after_seconds=settings.market_stream_stale_after_seconds,
            )
            app.state.market_stream.start()
        if settings.retention_worker_enabled:
            workers.append(
                asyncio.create_task(
                    app.state.retention.run_worker(settings.retention_purge_interval_seconds)
                )
            )
        if settings.backtests_enabled and settings.backtest_worker_enabled:
            workers.append(
                asyncio.create_task(
                    app.state.backtests.run_worker(settings.backtest_worker_poll_seconds)
                )
            )
        if settings.paper_enabled and settings.paper_worker_enabled:
            workers.append(
                asyncio.create_task(app.state.paper.run_worker(settings.paper_worker_poll_seconds))
            )
        if settings.agents_enabled and settings.agent_worker_enabled:
            workers.append(
                asyncio.create_task(app.state.agents.run_worker(settings.agent_worker_poll_seconds))
            )
        if settings.alerts_enabled and settings.alert_worker_enabled:
            workers.append(
                asyncio.create_task(app.state.alerts.run_worker(settings.alert_worker_poll_seconds))
            )
        if settings.alerts_enabled and settings.notify_worker_enabled:
            workers.append(
                asyncio.create_task(
                    app.state.alert_delivery.run_worker(settings.notify_worker_poll_seconds)
                )
            )
        if not settings.tester_sign_in_enabled:
            # Disabling tester sign-in ends every tester session, even ones an
            # earlier run issued, and a later re-enable does not revive them.
            from app.auth.tester import revoke_all_tester_sessions

            async def end_tester_sessions() -> None:
                # Retry until the revocation commits, so a database that is
                # down at startup cannot leave sessions to revive on re-enable.
                delay = 1.0
                while True:
                    try:
                        async with app.state.session_factory() as db:
                            ended = await revoke_all_tester_sessions(db, clock())
                        if ended:
                            logger.info("tester_sessions_ended", count=ended)
                        return
                    except Exception:
                        logger.warning("tester_sessions_end_failed", retry_in=delay)
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, 60.0)

            workers.append(asyncio.create_task(end_tester_sessions()))
        logger.info("startup", env=settings.app_env.value, version=__version__)
        try:
            yield
        finally:
            if app.state.market_stream is not None:
                await app.state.market_stream.stop()
                aclose = getattr(app.state.market_stream.source, "aclose", None)
                if aclose is not None:
                    await aclose()
            for worker in workers:
                worker.cancel()
            for worker in workers:
                with contextlib.suppress(asyncio.CancelledError):
                    await worker
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
            extra=exc.extra,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # The contract uses 400 INVALID_REQUEST, not FastAPI's default 422.
        return error_response(
            request, 400, "INVALID_REQUEST", "The request parameters are invalid."
        )

    # Routing errors (unknown path, wrong method) use the same error shape as
    # every contract route instead of FastAPI's {"detail": ...}.
    _http_error_codes = {
        404: ("NOT_FOUND", "API endpoint not found."),
        405: ("METHOD_NOT_ALLOWED", "Method not allowed for this endpoint."),
    }

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _http_error_codes.get(exc.status_code, ("HTTP_ERROR", "Request failed."))
        response = error_response(request, exc.status_code, code, message)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        # Log the traceback; never return it to the client.
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        return error_response(request, 500, "INTERNAL_ERROR", "Internal server error")

    # Last resort for errors raised by the middleware itself. Route errors are
    # answered by UnhandledErrorMiddleware below, inside the middleware stack.
    app.add_exception_handler(Exception, unhandled_exception)

    app.include_router(health.router)
    app.include_router(api_router)
    _drop_generated_422(app)

    # Middleware runs outermost-last-added. Order (outer -> inner):
    # RequestContext -> SecurityHeaders -> HostAllowlist -> CORS -> UnhandledError -> app
    app.add_middleware(UnhandledErrorMiddleware, handler=unhandled_exception)
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


def _build_stream_source(settings: Settings, clock: Clock) -> TickSource:
    if settings.market_stream_provider == "kite":
        from app.market.stream.kite import KiteTickSource

        if not (settings.kite_api_key and settings.kite_access_token_file):  # pragma: no cover
            raise RuntimeError("Kite credentials are not configured")  # settings validate this
        return KiteTickSource(
            api_key=settings.kite_api_key,
            access_token_file=settings.kite_access_token_file,
            clock=clock,
        )
    return MockTickSource(clock, tick_seconds=settings.market_stream_mock_tick_seconds)


def _drop_generated_422(app: FastAPI) -> None:
    """FastAPI documents a 422 HTTPValidationError on every operation with
    parameters, but invalid requests return 400 INVALID_REQUEST (see the
    RequestValidationError handler), so /openapi.json leaves the 422 out."""
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = generate()
            for operations in schema.get("paths", {}).values():
                for operation in operations.values():
                    operation.get("responses", {}).pop("422", None)
            schemas = schema.get("components", {}).get("schemas", {})
            for name in ("HTTPValidationError", "ValidationError"):
                schemas.pop(name, None)
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
