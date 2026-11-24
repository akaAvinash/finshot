"""/api/v1/strategies/preview endpoints, as specified in contracts/openapi.yaml.

Both require a valid session (401 first). The POST also requires a `session`
CSRF token, checked in a dependency before the command runs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request

from app.api.routes.auth import RequiredSession
from app.api.routes.brokers import csrf_session
from app.auth.service import SessionInfo
from app.strategies.schemas import StrategyCommand, StrategyResultOut, StrategySnapshotOut
from app.strategies.service import StrategyService

router = APIRouter(prefix="/api/v1/strategies/preview", tags=["strategies"])


def get_strategies(request: Request) -> StrategyService:
    service: StrategyService = request.app.state.strategies
    return service


Strategies = Annotated[StrategyService, Depends(get_strategies)]


@router.get(
    "",
    response_model=StrategyResultOut,
    operation_id="getStrategies",
    responses={401: {"description": "No valid session."}, 503: {"description": "Unavailable."}},
)
async def get_strategies_snapshot(
    session: RequiredSession, strategies: Strategies
) -> StrategyResultOut:
    return StrategyResultOut(data=await strategies.snapshot(session.user_id))


@router.post(
    "/commands",
    response_model=StrategySnapshotOut,
    operation_id="sendStrategyCommand",
    responses={
        400: {"description": "Malformed command or invalid parameters."},
        401: {"description": "No valid session."},
        403: {"description": "CSRF check failed."},
        404: {"description": "No such strategy for this user."},
        409: {"description": "The command does not fit the strategy's state."},
        503: {"description": "Unavailable."},
    },
)
async def send_strategy_command(
    session: Annotated[SessionInfo, Depends(csrf_session)],
    strategies: Strategies,
    command: Annotated[StrategyCommand, Body()],
) -> StrategySnapshotOut:
    return await strategies.command(session.user_id, command)
