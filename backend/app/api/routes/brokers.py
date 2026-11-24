"""/api/v1/brokers/preview endpoints, as specified in contracts/openapi.yaml.

Both require a valid session (401 first). The POST also requires a `session`
CSRF token, checked in a dependency so it runs before the action."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from app.api.routes.auth import Auth, RequiredSession
from app.auth.service import SessionInfo
from app.brokers.adapter import BrokerId
from app.brokers.schemas import BrokerActionRequest, BrokerResultOut, BrokerSnapshotOut
from app.brokers.service import BrokerService

router = APIRouter(prefix="/api/v1/brokers/preview", tags=["brokers"])


def get_brokers(request: Request) -> BrokerService:
    service: BrokerService = request.app.state.brokers
    return service


Brokers = Annotated[BrokerService, Depends(get_brokers)]


async def csrf_session(request: Request, auth: Auth, session: RequiredSession) -> SessionInfo:
    auth.enforce_csrf(request, session)
    return session


@router.get(
    "",
    response_model=BrokerResultOut,
    operation_id="getBrokers",
    responses={401: {"description": "No valid session."}, 503: {"description": "Unavailable."}},
)
async def get_brokers_snapshot(session: RequiredSession, brokers: Brokers) -> BrokerResultOut:
    return BrokerResultOut(data=await brokers.snapshot(session.user_id))


@router.post(
    "/{provider}/actions",
    response_model=BrokerSnapshotOut,
    operation_id="sendBrokerAction",
    responses={
        400: {"description": "Unknown provider or invalid action."},
        401: {"description": "No valid session."},
        403: {"description": "CSRF check failed."},
        409: {"description": "The action does not apply to the current state."},
        503: {"description": "Unavailable."},
    },
)
async def send_broker_action(
    session: Annotated[SessionInfo, Depends(csrf_session)],
    brokers: Brokers,
    provider: Annotated[BrokerId, Path()],
    body: BrokerActionRequest,
) -> BrokerSnapshotOut:
    return await brokers.apply(session.user_id, provider, body.action)
