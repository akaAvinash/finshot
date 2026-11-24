"""/api/v1/backtests/preview endpoints, as specified in contracts/openapi.yaml.

All require a valid session (401 first). Queuing a run also requires a
`session` CSRF token, checked in a dependency before the run is validated."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Request

from app.api.routes.auth import RequiredSession
from app.api.routes.brokers import csrf_session
from app.auth.service import SessionInfo
from app.backtests.schemas import BacktestConfig, BacktestRunOut, BacktestWorkspaceResultOut
from app.backtests.service import BacktestService

router = APIRouter(prefix="/api/v1/backtests/preview", tags=["backtests"])


def get_backtests(request: Request) -> BacktestService:
    service: BacktestService = request.app.state.backtests
    return service


Backtests = Annotated[BacktestService, Depends(get_backtests)]


@router.get(
    "",
    response_model=BacktestWorkspaceResultOut,
    operation_id="getBacktestWorkspace",
    responses={401: {"description": "No valid session."}, 503: {"description": "Unavailable."}},
)
async def get_backtest_workspace(
    session: RequiredSession, backtests: Backtests
) -> BacktestWorkspaceResultOut:
    return BacktestWorkspaceResultOut(data=await backtests.workspace(session.user_id))


@router.post(
    "/runs",
    status_code=202,
    response_model=BacktestRunOut,
    operation_id="startBacktest",
    responses={
        400: {"description": "Malformed body or a configuration that cannot be replayed."},
        401: {"description": "No valid session."},
        403: {"description": "CSRF check failed."},
        409: {"description": "Too many runs queued or running."},
        503: {"description": "Unavailable."},
    },
)
async def start_backtest(
    session: Annotated[SessionInfo, Depends(csrf_session)],
    backtests: Backtests,
    config: Annotated[BacktestConfig, Body()],
) -> BacktestRunOut:
    return await backtests.start(session.user_id, config)


@router.get(
    "/runs/{runId}",
    response_model=BacktestRunOut,
    operation_id="getBacktestRun",
    responses={
        401: {"description": "No valid session."},
        404: {"description": "No such run for this user."},
        503: {"description": "Unavailable."},
    },
)
async def get_backtest_run(
    session: RequiredSession,
    backtests: Backtests,
    run_id: Annotated[str, Path(alias="runId", min_length=1, max_length=64)],
) -> BacktestRunOut:
    return await backtests.run(session.user_id, run_id)
