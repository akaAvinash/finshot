"""/api/v1/auto-trading/paper endpoints, as specified in contracts/openapi.yaml.

Both require a valid session (401 first). Commands also require a `session`
CSRF token, checked in a dependency before the body is applied. Paper only:
nothing here reaches a broker."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request

from app.api.routes.auth import RequiredSession
from app.api.routes.brokers import csrf_session
from app.auth.service import SessionInfo
from app.paper.schemas import PaperCommand, PaperEmptyOut, PaperReadyOut, PaperSnapshotOut
from app.paper.service import PaperService

router = APIRouter(prefix="/api/v1/auto-trading/paper", tags=["paper trading"])


def get_paper(request: Request) -> PaperService:
    service: PaperService = request.app.state.paper
    return service


Paper = Annotated[PaperService, Depends(get_paper)]


@router.get(
    "",
    response_model=PaperReadyOut | PaperEmptyOut,
    operation_id="getPaperTrading",
    responses={401: {"description": "No valid session."}, 503: {"description": "Unavailable."}},
)
async def get_paper_trading(
    session: RequiredSession, paper: Paper
) -> PaperReadyOut | PaperEmptyOut:
    return await paper.workspace(session.user_id)


@router.post(
    "/commands",
    response_model=PaperSnapshotOut,
    operation_id="sendPaperCommand",
    responses={
        400: {"description": "Malformed command body."},
        401: {"description": "No valid session."},
        403: {"description": "CSRF check failed."},
        409: {"description": "The command does not fit the engine's state."},
        503: {"description": "Unavailable."},
    },
)
async def send_paper_command(
    session: Annotated[SessionInfo, Depends(csrf_session)],
    paper: Paper,
    command: Annotated[PaperCommand, Body()],
) -> PaperSnapshotOut:
    return await paper.command(session.user_id, command)
