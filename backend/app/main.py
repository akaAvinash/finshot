"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.router import api_router
from app.api.routes import health
from app.cache.redis import create_redis
from app.core.config import Environment, Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import (
    HostAllowlistMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.db.session import create_engine, create_session_factory

logger = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Engine and Redis client connect lazily, so startup does not fail if a
        # dependency is briefly down; /health/ready reports that instead.
        app.state.db_engine = create_engine(settings)
        app.state.session_factory = create_session_factory(app.state.db_engine)
        app.state.redis = create_redis(settings)
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

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        # Log the traceback; never return it to the client.
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

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
