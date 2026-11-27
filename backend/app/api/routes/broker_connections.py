"""/api/v1/broker-connections endpoints, as specified in contracts/openapi.yaml.

Reads need a valid session (401 first). Every write also needs a `session`
CSRF token, checked in a dependency before anything is read from the body.
Starting an authorization additionally needs step-up (401, TOTP setup, CSRF,
step-up, then 400/404/409)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from app.api.routes.auth import Auth, RequiredSession, ensure_stepped_up
from app.api.routes.brokers import csrf_session
from app.auth.service import SessionInfo
from app.brokers.connection_schemas import (
    AuthorizationCallbackIn,
    AuthorizationOut,
    AuthorizationResultOut,
    AuthorizationStartIn,
    ConnectionActionIn,
    PortfolioOut,
    SnapshotOut,
)
from app.brokers.connections import BrokerConnectionService

router = APIRouter(prefix="/api/v1/broker-connections", tags=["broker-connections"])


def get_connections(request: Request) -> BrokerConnectionService:
    service: BrokerConnectionService = request.app.state.broker_connections
    return service


Connections = Annotated[BrokerConnectionService, Depends(get_connections)]
CsrfSession = Annotated[SessionInfo, Depends(csrf_session)]
ConnectionId = Annotated[uuid.UUID, Path(alias="connectionId")]


async def start_session(request: Request, auth: Auth, session: RequiredSession) -> SessionInfo:
    """401, 403 TOTP_SETUP_REQUIRED, 403 CSRF_FAILED, 403 STEP_UP_REQUIRED, in
    this order, before the body is looked at."""
    auth.enforce_csrf(request, session)
    ensure_stepped_up(auth, session)
    return session


StartSession = Annotated[SessionInfo, Depends(start_session)]


@router.get("", response_model=SnapshotOut, operation_id="getBrokerConnections")
async def get_snapshot(session: RequiredSession, service: Connections) -> SnapshotOut:
    return await service.snapshot(session.user_id)


@router.post(
    "/authorizations",
    status_code=201,
    response_model=AuthorizationOut,
    operation_id="startBrokerAuthorization",
)
async def start_authorization(
    body: AuthorizationStartIn, session: StartSession, service: Connections
) -> AuthorizationOut:
    return await service.start_authorization(
        session.user_id,
        session.session_id,
        provider_id=body.provider_id,
        connection_id=body.connection_id,
    )


@router.post(
    "/authorizations/callback",
    response_model=AuthorizationResultOut,
    operation_id="completeBrokerAuthorization",
)
async def complete_authorization(
    body: AuthorizationCallbackIn, session: CsrfSession, service: Connections
) -> AuthorizationResultOut:
    return await service.complete_authorization(
        session.user_id, session.session_id, state=body.state, params=body.params
    )


@router.post(
    "/{connectionId}/actions",
    response_model=SnapshotOut,
    operation_id="sendBrokerConnectionAction",
)
async def send_action(
    connection_id: ConnectionId,
    body: ConnectionActionIn,
    session: CsrfSession,
    service: Connections,
) -> SnapshotOut:
    return await service.apply(session.user_id, connection_id, body.action)


@router.get(
    "/{connectionId}/portfolio",
    response_model=PortfolioOut,
    operation_id="getBrokerPortfolio",
)
async def get_portfolio(
    connection_id: ConnectionId, session: RequiredSession, service: Connections
) -> PortfolioOut:
    return await service.portfolio(session.user_id, connection_id)
