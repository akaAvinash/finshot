"""Liveness and readiness probes.

- /health/live: the process is up. Never touches dependencies.
- /health/ready: PostgreSQL and Redis both answer within the timeout.
  Returns 503 otherwise. Failure details go to the logs, not the response.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

import structlog
from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from app.cache.redis import ping_redis
from app.db.session import ping_database

router = APIRouter(prefix="/health", tags=["health"])
logger = structlog.get_logger(__name__)

CheckStatus = Literal["ok", "error"]


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ok", "error"]
    checks: dict[str, CheckStatus]


@router.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    return LivenessResponse(status="ok")


async def _run_check(
    name: str, probe: Callable[[], Awaitable[None]], limit_s: float
) -> CheckStatus:
    try:
        async with asyncio.timeout(limit_s):
            await probe()
    except Exception as exc:
        logger.warning("readiness_check_failed", check=name, error_type=type(exc).__name__)
        return "error"
    return "ok"


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "A dependency is unavailable"}},
)
async def ready(request: Request, response: Response) -> ReadinessResponse:
    state = request.app.state
    timeout = state.settings.health_check_timeout_seconds
    db_status, redis_status = await asyncio.gather(
        _run_check("database", lambda: ping_database(state.db_engine), timeout),
        _run_check("redis", lambda: ping_redis(state.redis), timeout),
    )
    checks: dict[str, CheckStatus] = {"database": db_status, "redis": redis_status}
    healthy = all(value == "ok" for value in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if healthy else "error", checks=checks)
